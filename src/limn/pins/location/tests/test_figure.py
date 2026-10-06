"""The figure branch of POST /api/pick (pins/location/figure.py): a drag on a figure document traced through
its build's element map. First the ladder rungs and the answer bodies as pure values, then the pick through the
location feature's HTTP entry on a real state folder with a figure build (tests/support/helpers_figure.py).
docs/handbook/api.md §그림 문서의 pick·핀 is the answer, region fallback included; docs/handbook/domain.md
§그림 문서의 요소 pick the rules.

Run: uv run pytest -q src/limn/pins/location/tests/test_figure.py
"""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from limn.builds import (
    ElementFact,
    ElementSelection,
    SelectionUnavailable,
    artifacts as limn_build,
    figure_map as figmap,
)
from limn.builds.figure_map import FigureMap, MapElement, MapPage, SourceRef
from limn.builds.queries import _element, select_element
from limn.pins.element import ElementImpl, PinElement
from limn.pins.location import resolve as pick_resolve, source as pick_source
from limn.pins.location.figure import (
    FigureFallback,
    PickedElement,
    drag_frac,
    element_rungs,
    pick_figure,
    pin_element as to_pin_element,
    read_source,
)
from limn.pins.location.http import PICK_WARNINGS, pick_answer
from limn.pins.location.input import PickRequest
from limn.pins.location.mapping import compute_levels, snippet
from limn.pins.location.range import SourceRange, snippet_api
from limn.pins.location.resolve import PickedRegion
from limn.platform import files
from limn.runtime.documents import Doc, RunPaths

from helpers import Base, fresh_runtime, jreq, pick, ps, req, split_resp
from helpers_figure import (
    AUGUST_BOX,
    BUILD1,
    BUILD2,
    EMPTY_BOX,
    JULY,
    JULY_BOX,
    SCRIPT,
    STRIP_BOX,
    b2_map,
    figure_doc,
    script_lines,
    write_build,
)

LINES = ["line %d" % i for i in range(1, 201)]
LATEX_KEYS = [
    "file",
    "name",
    "page",
    "lo",
    "hi",
    "raw_lo",
    "raw_hi",
    "kind",
    "via",
    "score",
    "warn",
    "n_lines",
    "snippet",
    "frac",
    "quote",
    "levels",
    "default_level",
    "overlaps",
    "pdf_build",
]
REGION_KEYS = [
    "doc",
    "kind",
    "view_only",
    "page",
    "frac",
    "pdf",
    "name",
    "quote",
    "n_chars",
    "warn",
    "overlaps",
    "pdf_build",
]
# A drag inside the July cell whose cover of it is 0.9999999999999961 in floating point, not 1.0.
INSIDE_JULY_BOX = (363.0, 123.3, 374.9, 139.7)


def el(eid, parent, frac, src=None, file="f.py", part=None, label=None):
    """A map element; src as (lo, hi) in file."""
    return MapElement(eid, parent, tuple(frac), None if src is None else SourceRef(file, *src), None, part, label)


ROOT = el("F", None, (0, 0, 1, 1), src=(1, 200))
CAL = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(80, 97), part="CalendarStrip", label="달력")
JUL = el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2), src=(88, 95), part="MonthCell", label="7월")


def rungs(*elements, drag=(0.3, 0.3, 0.0, 0.0), lines=LINES):
    """element_rungs for a click at drag on a page of the root and elements, with the chosen file's lines."""
    pg = MapPage(1, "F", None, (ROOT, *elements))
    return element_rungs(select_element(FigureMap("", "", (pg,)), 1, drag), lines)


class Rungs(unittest.TestCase):
    """The ladder of a map pick as rungs in the chosen element's file."""

    def test_one_rung_per_ladder_element_the_chosen_one_first(self):
        """The July cell, the strip and the figure: their lines, names, snippets and elements."""
        got = rungs(CAL, JUL)
        self.assertEqual(
            [(r.level, r.lo, r.hi, r.label) for r in got],
            [("el", 88, 95, "7월"), ("el2", 80, 97, "달력"), ("fig", 1, 200, "F")],
        )
        self.assertEqual(
            got[0].el, PinElement("F/cal/m07", ("F", "F/cal", "F/cal/m07"), "7월", "MonthCell", None, JUL.frac)
        )
        self.assertEqual(got[0].snippet, snippet(LINES, 88, 95))

    def test_same_lines_merge_into_the_inner_rung(self):
        """A strip drawn by the same lines as its cell: one rung, the cell's, with el2 listed as merged."""
        same = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(88, 95), part="CalendarStrip")
        got = rungs(same, JUL)
        self.assertEqual([(r.level, r.merged) for r in got], [("el", ("el2",)), ("fig", ())])
        self.assertEqual(got[0].el.id, "F/cal/m07")

    def test_a_rung_in_another_file_or_past_the_file_end_is_left_out(self):
        """A strip drawn in lib.py is not a rung of f.py; with 96 lines the strip (to 97) and figure (to 200) drop."""
        other = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(80, 97), file="lib.py")
        self.assertEqual([r.level for r in rungs(other, JUL)], ["el", "fig"])
        self.assertEqual([r.level for r in rungs(CAL, JUL, lines=LINES[:96])], ["el"])

    def test_no_rungs_when_the_chosen_element_has_no_usable_lines(self):
        """No src (D7), or lines past the end of the file: empty - the pick falls back to the region."""
        self.assertEqual(rungs(CAL, el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2))), ())
        self.assertEqual(rungs(CAL, JUL, lines=LINES[:90]), ())

    def test_a_rung_is_named_by_label_else_part_else_id(self):
        """Without a label the part names the rung; without either, the element id."""
        named_by_part = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(80, 97), part="CalendarStrip")
        bare = el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2), src=(88, 95))
        self.assertEqual([r.label for r in rungs(named_by_part, bare)], ["F/cal/m07", "CalendarStrip", "F"])

    def test_an_empty_label_and_part_name_a_rung_by_the_id_and_are_absent_from_its_element(self):
        """The map may hold "" for label and part (the parser keeps them): the rung is named by the id and its pin
        element has neither key, as for an element the map does not name."""
        blank = el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2), src=(88, 95), part="", label="")
        got = rungs(CAL, blank)
        self.assertEqual(got[0].label, "F/cal/m07")
        self.assertEqual((got[0].el.label, got[0].el.part), (None, None))
        self.assertEqual(
            got[0].el.to_record(),
            {"id": "F/cal/m07", "path": ["F", "F/cal", "F/cal/m07"], "frac": [0.2, 0.2, 0.2, 0.2]},
        )


def pin_element(page, el):
    """Adapt the map fixture to a completed provider fact before testing pin serialization."""
    return to_pin_element(_element(page, el))


class PinElements(unittest.TestCase):
    """pin_element: a map element as a pin records it."""

    PAGE = MapPage(1, "F", None, (ROOT, CAL, JUL))

    def test_an_element_carries_its_chain_names_implementation_and_box(self):
        """The ids from the root down, label, part, the shared implementation's file and lines, and the box."""
        shared = replace(JUL, impl=SourceRef("lib/c.py", 10, 20))
        self.assertEqual(
            pin_element(self.PAGE, shared),
            PinElement(
                "F/cal/m07", ("F", "F/cal", "F/cal/m07"), "7월", "MonthCell", ElementImpl("lib/c.py", 10, 20), JUL.frac
            ),
        )

    def test_the_root_is_a_chain_of_one(self):
        """The page root's path is just itself."""
        self.assertEqual(pin_element(self.PAGE, ROOT).path, ("F",))

    def test_an_empty_label_or_part_is_absent_not_an_empty_string(self):
        """ "" for either name is stored as absent (None) and answered without the key; a real name is kept; a part
        alone or a label alone leaves the other absent."""
        for label, part, want in (
            ("", "", (None, None)),
            ("", "MonthCell", (None, "MonthCell")),
            ("7월", "", ("7월", None)),
        ):
            with self.subTest(label=label, part=part):
                got = pin_element(self.PAGE, replace(JUL, label=label, part=part))
                self.assertEqual((got.label, got.part), want)
                self.assertEqual(
                    ("label" in got.to_record(), "part" in got.to_record()), (want[0] is not None, want[1] is not None)
                )


class DragFrac(unittest.TestCase):
    """drag_frac: the drag in points as page fractions."""

    def test_points_become_page_fractions(self):
        """A 36 x 24 point drag at (72, 48) on a 720 x 480 page."""
        self.assertEqual(drag_frac((72.0, 48.0, 108.0, 72.0), (720.0, 480.0)), (0.1, 0.1, 0.05, 0.05))

    def test_a_page_without_size_is_the_origin_point(self):
        """No size to divide by: the point (0, 0) - the pick then chooses by that point, never raises."""
        self.assertEqual(drag_frac((1.0, 1.0, 2.0, 2.0), (0.0, 480.0)), (0.0, 0.0, 0.0, 0.0))


class ReadSource(unittest.TestCase):
    """read_source: the one file a map names, read only when it lies inside the figure document's folder."""

    def setUp(self):
        """A manuscript root with the figure folder figs/ (a script, a directory, an empty file, a dot-named folder, a
        state folder) and a file beside it outside figs/."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.figs = self.root / "figs"
        (self.figs / "src").mkdir(parents=True)
        (self.figs / "src" / "a.py").write_text("one\ntwo\n", encoding="utf-8")
        (self.figs / "dir.py").mkdir()
        (self.figs / "src" / "empty.py").write_text("", encoding="utf-8")
        (self.figs / ".hidden").mkdir()
        (self.figs / ".hidden" / "a.py").write_text("secret\n", encoding="utf-8")
        (self.figs / "kept").mkdir()
        (self.figs / "kept" / "a.py").write_text("state\n", encoding="utf-8")
        self.beside = self.root / "beside.py"
        self.beside.write_text("outside\n", encoding="utf-8")
        self.state = self.root / "state"
        self.state.mkdir()
        paths = RunPaths(self.root, self.root / "main.tex", self.state)
        self.doc = Doc("fig", "그림", "figure", self.figs, self.figs / "out" / "m.json", paths=paths)

    def test_a_script_inside_the_folder_is_read_with_its_lines(self):
        """The checked file and its lines now."""
        got = read_source(self.doc, "src/a.py", self.root, self.state)
        self.assertIsNotNone(got)
        self.assertEqual((got[0].path, got[1]), (self.figs / "src" / "a.py", ["one", "two"]))

    def test_a_file_that_is_missing_a_directory_or_empty_is_not_read(self):
        """No such file, a directory and a file without lines answer None."""
        for rel in ("src/gone.py", "dir.py", "src/empty.py"):
            with self.subTest(rel=rel):
                self.assertIsNone(read_source(self.doc, rel, self.root, self.state))

    def test_a_dot_named_part_is_not_read(self):
        """The tree's rule for dot names holds inside the figure folder."""
        self.assertIsNone(read_source(self.doc, ".hidden/a.py", self.root, self.state))

    def test_a_symlink_leading_out_of_the_folder_is_not_read(self):
        """The link lies in the folder, its file in the manuscript but beside it: refused (tree_part of the folder)."""
        os.symlink(self.beside, self.figs / "src" / "link.py")
        self.assertIsNone(read_source(self.doc, "src/link.py", self.root, self.state))

    def test_a_file_in_the_state_folder_is_not_read(self):
        """A state folder inside the figure folder is never manuscript text."""
        self.assertIsNone(read_source(self.doc, "kept/a.py", self.root, self.figs / "kept"))
        self.assertIsNotNone(read_source(self.doc, "kept/a.py", self.root, self.state))


class SupplierAnswers(unittest.TestCase):
    """pick_figure tells the build owner's two answers apart without naming their classes: it asks only whether the
    answer has a `reason` member (limn.pins.needs.FigureMapUnavailable). Both tests pass the supplier's own values, so
    a supplier whose element selection gains a `reason` - which would send every pick to the region - fails here."""

    def setUp(self):
        """A manuscript root with the figure folder figs/ and a two-line script in it, and the figure document."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.figs = self.root / "figs"
        (self.figs / "src").mkdir(parents=True)
        (self.figs / "src" / "a.py").write_text("one\ntwo\n", encoding="utf-8")
        self.state = self.root / "state"
        self.state.mkdir()
        paths = RunPaths(self.root, self.root / "main.tex", self.state)
        self.doc = Doc("fig", "그림", "figure", self.figs, self.figs / "out" / "m.json", paths=paths)

    def pick(self, selection):
        """pick_figure for a drag on page 1 of the build `pages` answered with selection; no pin overlaps it and
        nothing is being redrawn."""
        box, size = (0.0, 0.0, 72.0, 48.0), (720.0, 480.0)
        pdir = self.figs / "pages"
        return pick_figure(
            self.doc, 1, box, size, None, pdir, selection, self.root, self.state, lambda file, lo, hi: [], False
        )

    def test_the_suppliers_unavailable_answer_falls_back_without_an_element(self):
        """limn.builds.SelectionUnavailable is the map fallback: its reason, and no element."""
        self.assertEqual(self.pick(SelectionUnavailable()), FigureFallback("figure_map_unavailable", None))

    def test_the_suppliers_selection_is_traced_to_the_chosen_elements_lines(self):
        """limn.builds.ElementSelection is an element pick: the chosen element, its kind and its script lines."""
        cell = ElementFact(
            "F/a", ("F", "F/a"), "칸", "Cell", None, (0.0, 0.0, 0.1, 0.1), ("src/a.py", 1, 2), ("", "칸")
        )
        got = self.pick(ElementSelection(cell, "el:Cell", 1.0, (("el", cell),)))
        self.assertIsInstance(got, PickedElement)
        self.assertEqual((got.el.id, got.kind, got.n_lines), ("F/a", "el:Cell", 2))
        self.assertEqual([(r.level, r.lo, r.hi) for r in got.rungs], [("el", 1, 2)])


class RegionBodies(unittest.TestCase):
    """The region body: unchanged for a view-only document, with el and the reason first for a figure fallback."""

    REGION = PickedRegion("rv", 1, [0.1, 0.1, 0.2, 0.2], "review.pdf", "review.pdf", "", 0, True, False, "pages")

    def test_a_view_only_region_body_is_unchanged(self):
        """Same keys in the same order, no el, the blank-region sentence only."""
        body = pick_answer(self.REGION)
        self.assertEqual(list(body), REGION_KEYS)
        self.assertEqual(body["warn"], PICK_WARNINGS["blank"])

    def test_a_figure_fallback_names_its_reason_first_and_adds_the_element(self):
        """The reason's sentence leads the warn, and el and the names of its path follow the contract keys."""
        el08 = PinElement("B2/m08", ("B2", "B2/m08"))
        body = pick_answer(replace(self.REGION, el=el08, fallback="element_without_source", path_names=("", "8월")))
        self.assertEqual(list(body), REGION_KEYS + ["el", "path_names"])
        self.assertEqual(body["warn"], PICK_WARNINGS["element_without_source"] + " " + PICK_WARNINGS["blank"])
        self.assertEqual(body["el"], {"id": "B2/m08", "path": ["B2", "B2/m08"]})
        self.assertEqual(body["path_names"], ["", "8월"])

    def test_a_fallback_without_an_element_has_no_el_and_a_redraw_sentence_comes_last(self):
        """figure_map_unavailable names no element (no el key); with a text-bearing region being redrawn the warn is
        the reason, then the redraw sentence."""
        body = pick_answer(replace(self.REGION, blank=False, redrawing=True, fallback="figure_map_unavailable"))
        self.assertEqual(list(body), REGION_KEYS)
        self.assertEqual(body["warn"], PICK_WARNINGS["figure_map_unavailable"] + " " + PICK_WARNINGS["redrawing"])


class SnippetLadder(unittest.TestCase):
    """snippet_api: the source ladder (compute_levels) where a document's ladder comes from its text; only the raw
    rung where it comes from an element map (a figure's script, whose element ladder is the pick's)."""

    TEX = ["\\begin{table}", "a", "", "b", "\\end{table}"]

    def test_a_map_ladder_document_gets_only_the_raw_rung(self):
        """Python lines: one raw rung for the range, and it is the default - no paragraph or environment rung."""
        rng = SourceRange(Path("/ms/figs/src/a.py"), ["x = 1", "", "y = 2", "z = 3"], 3, 4)
        out = snippet_api(rng, True, ("table",), source_ladder=False)
        self.assertEqual(
            out["levels"],
            [{"level": "raw", "lo": 3, "hi": 4, "label": "드래그한 줄", "n": 2, "snippet": snippet(rng.lines, 3, 4)}],
        )
        self.assertEqual(out["default_level"], "raw")

    def test_a_source_ladder_document_keeps_compute_levels(self):
        """LaTeX lines: the ladder is compute_levels', unchanged."""
        rng = SourceRange(Path("/ms/main.tex"), self.TEX, 2, 2)
        out = snippet_api(rng, True, ("table",), source_ladder=True)
        want = compute_levels(self.TEX, 2, 2, ("table",))
        self.assertEqual((out["levels"], out["default_level"]), (want["levels"], want["default_level"]))

    def test_the_source_ladder_is_the_default(self):
        """Without the parameter a document's ladder is compute_levels' (every caller before figures)."""
        rng = SourceRange(Path("/ms/main.tex"), self.TEX, 2, 2)
        self.assertEqual(snippet_api(rng, True, ("table",)), snippet_api(rng, True, ("table",), source_ladder=True))

    def test_no_ladder_is_computed_unless_levels_are_asked_for(self):
        """levels false: neither ladder is in the answer, whichever the document's kind."""
        rng = SourceRange(Path("/ms/figs/src/a.py"), ["x = 1", "y = 2"], 1, 2)
        for source_ladder in (True, False):
            out = snippet_api(rng, False, ("table",), source_ladder=source_ladder)
            self.assertNotIn("levels", out)
            self.assertNotIn("default_level", out)

    def test_the_latex_ladder_is_never_run_for_a_map_ladder_document(self):
        """source_ladder false never calls compute_levels, however the lines look like LaTeX."""
        rng = SourceRange(Path("/ms/figs/src/a.py"), self.TEX, 2, 2)
        with mock.patch("limn.pins.location.range.compute_levels", side_effect=AssertionError("LaTeX rules")):
            out = snippet_api(rng, True, ("table",), source_ladder=False)
        self.assertEqual([lv["level"] for lv in out["levels"]], ["raw"])


class FigurePick(Base):
    """POST /api/pick on figure document fig through the location feature, with a real build and scripts."""

    def setUp(self):
        """A LaTeX document ms and the figure document fig, whose build BUILD1 with the example map is on screen."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())
        self.script = self.fig.src / "src" / "B2_calendar.py"

    def drag(self, box, build=BUILD1, page=1, **extra):
        """POST /api/pick of box (points) on page of build; pdftotext answers no text and SyncTeX must not run."""
        x0, y0, x1, y1 = box
        body = {"doc": "fig", "page": page, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": build, **extra}
        with (
            mock.patch.object(pick_source, "region_text", return_value=""),
            mock.patch.object(pick_source, "by_synctex", side_effect=AssertionError("no SyncTeX on a figure")),
        ):
            return pick(body, doc=self.fig)

    def test_a_drag_on_an_element_answers_its_lines_through_the_map(self):
        """The July cell: the line body in the contract's key order plus el, via map, the cell's call lines, its kind
        and name, and the ladder cell - strip - figure; pdftotext is never run for a map pick."""
        with mock.patch.object(pick_source, "region_text", side_effect=AssertionError("no pdftotext on a map pick")):
            x0, y0, x1, y1 = JULY_BOX
            d = pick(
                {"doc": "fig", "page": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": BUILD1}, doc=self.fig
            )
        self.assertEqual(list(d), LATEX_KEYS + ["el", "path_names"])
        self.assertEqual(
            (d["file"], d["name"], d["lo"], d["hi"], d["raw_lo"], d["raw_hi"], d["n_lines"]),
            (str(self.script), "B2_calendar.py", 88, 95, 88, 95, 140),
        )
        self.assertEqual(
            (d["kind"], d["via"], d["score"], d["quote"], d["default_level"], d["warn"], d["pdf_build"]),
            ("el:MonthCell", "map", 1.0, "7월", "el", "", BUILD1),
        )
        self.assertEqual(
            d["el"],
            {
                "id": "B2/calendar/m07",
                "path": ["B2", "B2/calendar", "B2/calendar/m07"],
                "label": "7월",
                "part": "MonthCell",
                "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
                "frac": [0.47, 0.18, 0.07, 0.12],
            },
        )
        self.assertEqual(
            [(lv["level"], lv["lo"], lv["hi"], lv["label"], lv["n"], lv["el"]["id"]) for lv in d["levels"]],
            [
                ("el", 88, 95, "7월", 8, "B2/calendar/m07"),
                ("el2", 80, 97, "달력", 18, "B2/calendar"),
                ("fig", 12, 140, "B2", 129, "B2"),
            ],
        )
        self.assertTrue(d["snippet"].startswith("   88      # July cell"))

    def test_a_drag_on_empty_space_picks_the_whole_figure(self):
        """No element but the root under the drag: kind figure, default level fig, the figure's lines."""
        d = self.drag(EMPTY_BOX)
        self.assertEqual((d["kind"], d["default_level"], d["lo"], d["hi"]), ("figure", "fig", 12, 140))
        self.assertEqual([lv["level"] for lv in d["levels"]], ["fig"])
        self.assertEqual(d["el"], {"id": "B2", "path": ["B2"], "frac": [0, 0, 1, 1]})

    def test_an_element_drawn_without_code_answers_the_region_with_the_element(self):
        """The August cell has no src: the region body, its reason first, and the element (D7)."""
        d = self.drag(AUGUST_BOX)
        self.assertEqual((d["kind"], d["el"]["id"]), ("region", "B2/calendar/m08"))
        self.assertTrue(d["warn"].startswith(PICK_WARNINGS["element_without_source"]))
        self.assertNotIn("lo", d)

    def test_every_answer_with_an_element_names_each_element_on_its_path(self):
        """path_names gives, root first, each element of el.path the name the map gives it - label, else part - and
        "" where it gives none (the figure's root): for the July cell's lines, the August cell's region (whose strip
        has no rung to name it) and the whole figure."""
        for box, path, names in (
            (JULY_BOX, ["B2", "B2/calendar", "B2/calendar/m07"], ["", "달력", "7월"]),
            (AUGUST_BOX, ["B2", "B2/calendar", "B2/calendar/m08"], ["", "달력", "8월"]),
            (EMPTY_BOX, ["B2"], [""]),
        ):
            with self.subTest(box=box):
                d = self.drag(box)
                self.assertEqual((d["el"]["path"], d["path_names"]), (path, names))

    def test_no_loadable_map_answers_the_region_without_an_element(self):
        """No map copy, a copy the parser refuses, or a page the map does not describe: the region, no el."""
        copy = self.fig.dir / BUILD1 / limn_build.FIGMAP_NAME
        copy.unlink()
        for setup in (lambda: None, lambda: copy.write_text("not json", encoding="utf-8")):
            setup()
            d = self.drag(JULY_BOX)
            self.assertTrue(d["warn"].startswith(PICK_WARNINGS["figure_map_unavailable"]), d)
            self.assertNotIn("el", d)
        write_build(self.fig, BUILD2, b2_map(), pages=2)
        d = self.drag(JULY_BOX, build=BUILD2, page=2)
        self.assertTrue(d["warn"].startswith(PICK_WARNINGS["figure_map_unavailable"]))

    def test_a_drag_on_an_older_build_is_traced_through_that_builds_map(self):
        """After a re-render moved the July cell, a drag made on the old screen still finds the July cell (its build's
        map), while the same box on the new build lands on the strip."""
        write_build(self.fig, BUILD2, b2_map(july=(0.6, 0.18, 0.07, 0.12)))
        self.assertEqual(self.drag(JULY_BOX, build=BUILD1)["el"]["id"], "B2/calendar/m07")
        self.assertEqual(self.drag(JULY_BOX, build=BUILD2)["el"]["id"], "B2/calendar")

    def test_lines_past_the_end_of_the_script_fall_back_or_drop_the_rung(self):
        """The script shortened after the render: at 96 lines the cell's call still fits but the strip and figure do
        not (one rung); at 90 lines the cell does not fit either - the region with the cell."""
        self.script.write_text("\n".join(script_lines(96)) + "\n", encoding="utf-8")
        d = self.drag(JULY_BOX)
        self.assertEqual([lv["level"] for lv in d["levels"]], ["el"])
        self.script.write_text("\n".join(script_lines(90)) + "\n", encoding="utf-8")
        d = self.drag(JULY_BOX)
        self.assertEqual((d["kind"], d["el"]["id"]), ("region", "B2/calendar/m07"))
        self.assertTrue(d["warn"].startswith(PICK_WARNINGS["element_without_source"]))

    def test_a_script_that_links_out_of_the_folder_answers_alike_from_a_warm_and_a_cold_cache(self):
        """The July cell's script is a link out of figs/ to a manuscript file beside it. With the run's map cache warm
        (a first drag parsed the map while the script was still inside) or cold (a restart: the link was already there
        for the first drag), the answer is the same: the region body with the element B2/calendar/m07 and the
        element_without_source sentence - never figure_map_unavailable - and the file the link leads to is never
        opened. The two whole answers are equal. The folder is judged when the script is read, not when the map is
        parsed."""
        outside = self.src / "elsewhere.py"
        outside.write_text("\n".join(script_lines()) + "\n", encoding="utf-8")
        real, opened = files.ManuscriptFile.snapshot, []
        answers = {}

        def spy(checked):
            """Record the file read, then read it."""
            opened.append(checked.path)
            return real(checked)

        for cache in ("warm", "cold"):
            with (
                self.subTest(cache=cache),
                mock.patch.object(files.ManuscriptFile, "snapshot", spy),
                mock.patch.object(limn_build, "parse_map", wraps=figmap.parse_map) as parsed,
            ):
                self.script.unlink(missing_ok=True)
                self.script.write_text("\n".join(script_lines()) + "\n", encoding="utf-8")
                fresh_runtime()
                opened.clear()
                if cache == "warm":
                    first = self.drag(JULY_BOX)
                    self.assertEqual(
                        (first["kind"], first["el"]["id"], opened), ("el:MonthCell", "B2/calendar/m07", [self.script])
                    )
                self.script.unlink()
                os.symlink(outside, self.script)
                opened.clear()
                d = answers[cache] = self.drag(JULY_BOX)
                self.assertEqual(parsed.call_count, 1)  # warm: the first drag's parse served both; cold: this one
                self.assertEqual((d["kind"], d["el"]["id"]), ("region", "B2/calendar/m07"))
                self.assertTrue(d["warn"].startswith(PICK_WARNINGS["element_without_source"]), d["warn"])
                self.assertEqual(opened, [])
        self.assertEqual(answers["warm"], answers["cold"])

    def test_a_script_that_links_out_of_the_folder_costs_only_the_elements_drawn_by_it(self):
        """The strip is drawn by src/B2_calendar.py, which is a link out of figs/, and the July cell by src/july.py,
        which is inside. The map is one map: a drag on the July cell still answers its lines and its ladder (the strip
        and the figure, drawn in the other file, are no rungs of it), while a drag on the strip alone answers the region
        with the strip and the element_without_source sentence."""
        fmap = b2_map()
        july = next(e for e in fmap["pages"][0]["elements"] if e["id"] == "B2/calendar/m07")
        july["src"]["file"] = "src/july.py"
        july_script = self.fig.src / "src" / "july.py"
        july_script.write_text("\n".join(script_lines()) + "\n", encoding="utf-8")
        write_build(self.fig, BUILD1, fmap)
        outside = self.src / "elsewhere.py"
        outside.write_text("\n".join(script_lines()) + "\n", encoding="utf-8")
        self.script.unlink()
        os.symlink(outside, self.script)
        real, opened = files.ManuscriptFile.snapshot, []

        def spy(checked):
            """Record the file read, then read it."""
            opened.append(checked.path)
            return real(checked)

        with mock.patch.object(files.ManuscriptFile, "snapshot", spy):
            cell = self.drag(JULY_BOX)
            strip = self.drag(STRIP_BOX)
        self.assertEqual(
            (cell["kind"], cell["el"]["id"], cell["file"], cell["lo"], cell["hi"]),
            ("el:MonthCell", "B2/calendar/m07", str(july_script), 88, 95),
        )
        self.assertEqual([lv["level"] for lv in cell["levels"]], ["el"])
        self.assertEqual((strip["kind"], strip["el"]["id"]), ("region", "B2/calendar"))
        self.assertTrue(strip["warn"].startswith(PICK_WARNINGS["element_without_source"]), strip["warn"])
        self.assertEqual(opened, [july_script])

    def test_a_small_cover_warns_like_a_weak_match(self):
        """A tall drag across two cells and far past the strip picks the strip (their common ancestor) with a cover of
        22%: the weak-match sentence."""
        d = self.drag((345.6, 24.0, 432.0, 288.0))
        self.assertEqual((d["el"]["id"], d["score"]), ("B2/calendar", 0.22))
        self.assertTrue(d["warn"].startswith("이 영역은 원문 대조가 약합니다(22%)."))

    def test_a_drag_fully_inside_a_cell_answers_a_score_of_exactly_one_in_the_json_body(self):
        """Full containment computes a cover a hair under 1.0 (0.9999999999999961 for the box here): the body a client
        reads over HTTP holds the score rounded to two decimals, 1.0, and no warning."""
        body = {"doc": "fig", "page": 1, "pdf_build": BUILD1}
        body.update(zip(("x0", "y0", "x1", "y1"), INSIDE_JULY_BOX, strict=True))
        from limn.builds import queries

        real, picks = queries.pick_element, []

        def record(page, drag):
            """pick_element, keeping what it chose."""
            picks.append(real(page, drag))
            return picks[-1]

        with (
            mock.patch.object(pick_source, "region_text", side_effect=AssertionError("no pdftotext on a map pick")),
            mock.patch.object(queries, "pick_element", record),
        ):
            code, _, raw = split_resp(self.talk(jreq("POST", "/api/pick", body)))
        self.assertEqual(code, 200, raw)
        self.assertLess(picks[0].score, 1.0)
        d = json.loads(raw)
        self.assertEqual((d["el"]["id"], d["score"], d["warn"]), ("B2/calendar/m07", 1.0, ""))
        self.assertIn(b'"score": 1.0', raw)

    def test_a_fallback_parses_the_map_copy_once_for_the_element_and_the_region_alike(self):
        """A drag that falls back - the August cell without code, then a copy the parser refuses - reads the copy once
        (the region's PDF comes through the run's cache too), and a second drag on either parses nothing."""
        write_build(self.fig, BUILD2, {"format": "not-a-map"})
        for build, box, reason in (
            (BUILD1, AUGUST_BOX, "element_without_source"),
            (BUILD2, JULY_BOX, "figure_map_unavailable"),
        ):
            with (
                self.subTest(build=build),
                mock.patch.object(limn_build, "parse_map", wraps=figmap.parse_map) as parsed,
            ):
                d = self.drag(box, build=build)
                self.assertTrue(d["warn"].startswith(PICK_WARNINGS[reason]), d)
                self.assertEqual(parsed.call_count, 1)
                self.drag(box, build=build)
                self.assertEqual(parsed.call_count, 1)

    def test_a_fallback_names_the_pdf_of_the_map_it_was_traced_on(self):
        """The region a fallback answers is named after the PDF of the drag's own build's map."""
        d = self.drag(AUGUST_BOX)
        self.assertEqual((d["pdf"], d["name"]), ("figs/out/figures.pdf", "figures.pdf"))

    def test_an_element_with_empty_label_and_part_is_answered_without_either_key(self):
        """A map whose July cell has "" for label and part: the pick's el, and each rung's el, have neither key; the
        kind is el:? and the quote and rung name fall back to none and the id."""
        fmap = b2_map()
        july = next(e for e in fmap["pages"][0]["elements"] if e["id"] == "B2/calendar/m07")
        july["label"] = july["part"] = ""
        write_build(self.fig, BUILD2, fmap)
        d = self.drag(JULY_BOX, build=BUILD2)
        self.assertEqual((d["kind"], d["quote"], d["levels"][0]["label"]), ("el:?", "", "B2/calendar/m07"))
        want = {
            "id": "B2/calendar/m07",
            "path": ["B2", "B2/calendar", "B2/calendar/m07"],
            "impl": d["el"]["impl"],
            "frac": list(JULY),
        }
        self.assertEqual(d["el"], want)
        self.assertEqual(d["levels"][0]["el"], want)

    def test_the_edit_cards_ladder_on_a_figure_script_is_the_raw_rung_only(self):
        """GET /api/snippet?levels=1 on the figure's script: one raw rung; on the LaTeX document the paragraph rung is
        still there."""
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=fig&file=%s&lo=88&hi=95&levels=1" % SCRIPT)))
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertEqual(([lv["level"] for lv in d["levels"]], d["default_level"]), (["raw"], "raw"))
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=ms&file=main.tex&lo=4&hi=4&levels=1")))
        self.assertIn("para", [lv["level"] for lv in json.loads(body)["levels"]])

    def test_a_figure_snippet_without_levels_has_no_ladder(self):
        """GET /api/snippet on the script without levels answers the lines alone, as for a LaTeX document."""
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=fig&file=%s&lo=88&hi=95" % SCRIPT)))
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertNotIn("levels", d)
        self.assertNotIn("default_level", d)


class Dispatch(Base):
    """resolve.pick asks for a figure map only for a document that has an element map."""

    def setUp(self):
        """The LaTeX document ms and a view-only PDF document rv, with a spy standing for the map lookup."""
        super().setUp()
        self.rv = Doc("rv", "리뷰", "pdf", self.src, self.src / "review.pdf", paths=ps.APP.C.paths)
        self.asked = mock.Mock(return_value=None)
        self.ctx = pick_resolve.PickContext(
            self.src, ps.APP.C.envs, ps.APP.C.state, ps.APP.RT.token_cache, lambda f, lo, hi: [], self.asked
        )
        self.request = PickRequest(self.src, 1, (10.0, 10.0, 40.0, 30.0), (720.0, 480.0), None)

    def test_a_document_without_an_element_map_never_asks_for_one(self):
        """A LaTeX document and a view-only PDF are picked as before, and the lookup is not called for either."""
        ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        with (
            mock.patch.object(pick_source, "region_text", return_value=""),
            mock.patch.object(pick_source, "by_synctex", return_value=None),
        ):
            pick_resolve.pick(ms, self.request, self.ctx)
            region = pick_resolve.pick(self.rv, self.request, self.ctx)
        self.assertIsInstance(region, PickedRegion)
        self.assertEqual((region.el, region.fallback), (None, None))
        self.asked.assert_not_called()


if __name__ == "__main__":
    unittest.main()

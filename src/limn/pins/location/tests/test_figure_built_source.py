"""A drag on a figure build whose drawing script was edited since answers where the element's code stands now
(docs/handbook/domain.md §그림 문서의 요소 pick, docs/handbook/build-sync.md §빌드가 읽은 원고 줄).

A figure's element map numbers the lines of the script as it was rendered. The import keeps those lines with the pages
(the build's source record), and the pick carries each rung's range over to the script as it is today. Every build here
is imported through the tracked build (tests/support/helpers_figure.py import_build: only pdftoppm is stood in for), so
the record is the one an import writes, and the pick is asked over the location feature's HTTP entry.

Run: uv run pytest -q src/limn/pins/location/tests/test_figure_built_source.py
"""

from unittest import mock

from limn.builds import built_source
from limn.builds.artifacts import BuildOk
from limn.pins.location import source as pick_source
from limn.pins.location.http import PICK_WARNINGS
from limn.runtime.documents import Doc

from helpers import Base, pick, ps
from helpers_figure import BUILD1, BUILD2, JULY_BOX, b2_map, figure_doc, import_build, script_lines, write_build

ADDED = ["added_%d = setup(%d)" % (i, i) for i in range(1, 6)]  # five lines put into the script above the strip
ADDED_AT = 20  # they follow this line of the script, inside the figure's function and above every inner element


def moved_map(by: int) -> dict:
    """b2_map() as a re-render of the script with `by` lines added at ADDED_AT writes it: the figure ends `by` lines
    later, the strip and the July cell start and end `by` lines later."""
    fmap = b2_map()
    for element in fmap["pages"][0]["elements"]:
        src = element.get("src")
        if src is None:
            continue
        if src["lo"] > ADDED_AT:
            src["lo"] += by
        src["hi"] += by
    return fmap


class FigurePickAfterAScriptEdit(Base):
    """Figure document fig imported as BUILD1 from the example script, which is then edited."""

    def setUp(self):
        """A LaTeX document ms and the figure document fig, whose build BUILD1 was imported from script_lines()."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        self.script = self.fig.src / "src" / "B2_calendar.py"
        self.assertIsInstance(import_build(ps.APP, self.fig, BUILD1, b2_map()), BuildOk)

    def add_lines(self):
        """Put ADDED into the script after line ADDED_AT: every element below it now starts five lines later."""
        lines = script_lines()
        self.script.write_text("\n".join(lines[:ADDED_AT] + ADDED + lines[ADDED_AT:]) + "\n", encoding="utf-8")

    def drag(self, box, build):
        """POST /api/pick of box (points) on page 1 of build; pdftotext answers no text and SyncTeX must not run."""
        x0, y0, x1, y1 = box
        body = {"doc": "fig", "page": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": build}
        with (
            mock.patch.object(pick_source, "region_text", return_value=""),
            mock.patch.object(pick_source, "by_synctex", side_effect=AssertionError("no SyncTeX on a figure")),
        ):
            return pick(body, doc=self.fig)

    def code_of(self, answer):
        """The lines of the script, as it is now, that a line answer names."""
        now = self.script.read_text(encoding="utf-8").splitlines()
        return now[answer["lo"] - 1 : answer["hi"]]

    def test_a_drag_on_an_older_build_answers_the_cells_code_after_lines_were_added_above_it(self):
        """The script gains five lines above the strip and is rendered again (BUILD2). A drag made on BUILD1 - a pin
        queued offline, a screen not yet switched - is traced through BUILD1's map, which says 88-95: the answer is
        93-100, the July cell's call as it stands now, and every outer rung moved with its code."""
        self.add_lines()
        self.assertIsInstance(import_build(ps.APP, self.fig, BUILD2, moved_map(5)), BuildOk)
        d = self.drag(JULY_BOX, BUILD1)
        self.assertEqual((d["via"], d["el"]["id"], d["pdf_build"]), ("map", "B2/calendar/m07", BUILD1))
        self.assertEqual((d["lo"], d["hi"], d["raw_lo"], d["raw_hi"], d["n_lines"]), (93, 100, 93, 100, 145))
        self.assertEqual(self.code_of(d), script_lines()[87:95])
        self.assertTrue(d["snippet"].startswith("   93      # July cell"))
        ladder = [(lv["level"], lv["lo"], lv["hi"]) for lv in d["levels"]]
        self.assertEqual(ladder, [("el", 93, 100), ("el2", 85, 102), ("fig", 12, 145)])
        self.assertEqual(d["warn"], "")

    def test_the_same_drag_on_the_new_build_answers_the_same_lines(self):
        """The control: BUILD2's own map already says 93-100, and its record is the script as it is now."""
        self.add_lines()
        import_build(ps.APP, self.fig, BUILD2, moved_map(5))
        d = self.drag(JULY_BOX, BUILD2)
        self.assertEqual((d["lo"], d["hi"], d["n_lines"]), (93, 100, 145))

    def test_a_script_edited_and_not_rendered_again_is_answered_at_the_cells_code(self):
        """The build on screen is older than the script (an agent edited it and has not rendered yet): its map still
        says 88-95, and the answer is where those lines stand now."""
        self.add_lines()
        d = self.drag(JULY_BOX, BUILD1)
        self.assertEqual((d["lo"], d["hi"]), (93, 100))
        self.assertEqual(self.code_of(d), script_lines()[87:95])

    def test_an_unchanged_script_is_answered_with_the_maps_own_lines(self):
        """Nothing was edited: the record and the script are the same lines, and the map's numbers stand."""
        d = self.drag(JULY_BOX, BUILD1)
        self.assertEqual((d["lo"], d["hi"], d["n_lines"]), (88, 95, 140))
        self.assertEqual([(lv["lo"], lv["hi"]) for lv in d["levels"]], [(88, 95), (80, 97), (12, 140)])

    def test_code_removed_since_the_import_answers_the_region_with_the_element(self):
        """The July cell's call was deleted from the script: no line of it stands, so the answer is the region with the
        cell and the sentence that its code was not found - never the lines that moved into its numbers."""
        lines = script_lines()
        self.script.write_text("\n".join(lines[:87] + lines[95:]) + "\n", encoding="utf-8")
        d = self.drag(JULY_BOX, BUILD1)
        self.assertEqual((d["kind"], d["el"]["id"]), ("region", "B2/calendar/m07"))
        self.assertTrue(d["warn"].startswith(PICK_WARNINGS["element_without_source"]))

    def test_an_outer_rung_whose_code_is_gone_is_left_out_of_the_ladder(self):
        """Every line of the strip outside the cell's call was rewritten and the cell's call kept: the cell's rung and
        the figure's stand; the strip's rung, carried, spans only the cell's lines and merges into the cell's."""
        lines = script_lines()
        for no in (*range(80, 88), 96, 97):
            lines[no - 1] = "rewritten_%03d = other(%d)" % (no, no)
        self.script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        d = self.drag(JULY_BOX, BUILD1)
        self.assertEqual([(lv["level"], lv["lo"], lv["hi"]) for lv in d["levels"]], [("el", 88, 95), ("fig", 12, 140)])
        self.assertEqual(d["levels"][0].get("merged"), ["el2"])

    def test_a_build_without_a_record_is_answered_with_the_maps_numbers(self):
        """A build imported by an older Limn kept no record: the map's numbers are used on the script as they are,
        as before - here on the lines that moved into them."""
        (self.fig.dir / BUILD1 / built_source.SOURCE_NAME).unlink()
        self.add_lines()
        d = self.drag(JULY_BOX, BUILD1)
        self.assertEqual((d["lo"], d["hi"]), (88, 95))

    def test_a_record_the_maps_lines_do_not_fit_in_gives_no_rung(self):
        """A record shorter than the map's range is not the script that map was rendered from (the script was cut
        between the render and the import): the element has no lines to carry, so the answer is the region."""
        write_build(self.fig, BUILD2, b2_map())
        record = built_source.encode({"src/B2_calendar.py": script_lines(90)})
        (self.fig.dir / BUILD2 / built_source.SOURCE_NAME).write_text(record, encoding="utf-8")
        d = self.drag(JULY_BOX, BUILD2)
        self.assertEqual((d["kind"], d["el"]["id"]), ("region", "B2/calendar/m07"))

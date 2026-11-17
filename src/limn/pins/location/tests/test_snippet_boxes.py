"""The boxes every rung of GET /api/snippet?levels=1 carries - where that rung's line range prints on the PDF
(docs/adr/0045-pin-marks-follow-the-range.md).

The viewer reads this route whenever the person moves up the range ladder or types a range by hand, so each rung
carries the mark of its own range and the box follows the range with no second round trip. The forward pass runs
`synctex view` once per line of text of a rung, so these tests stub limn.pins.location.source.synctex_view and watch
which lines and which file name it is asked for. That watching is the point: the line cap holds per rung, a rung whose
range no longer stands on the build's lines is asked for nothing, a build that kept no record of the lines it read is
asked nothing at all - unlike a pick, which holds SyncTeX's own answer in that build's numbers - and a document whose
rungs are not manuscript lines (a figure's drawing script) asks nothing either.

Run: uv run pytest -q src/limn/pins/location/tests/test_snippet_boxes.py
"""

import json
from unittest import mock

from limn.builds import built_source
from limn.pins.location import (
    http as location_http,
    input as location_input,
    range as source_range,
    resolve as pick_resolve,
    source as pick_source,
)
from limn.pins.location.mapping import BOX_LIMIT
from limn.runtime.documents import Doc

import helpers_figure
from helpers import TEX, Base, ps, req, split_resp

PAGE_PX = (1500, 1000)  # the page image the build on screen left
PAGE_W, PAGE_H = 720.0, 480.0  # its size in points at the fixture's 150 dpi
PAGES = ((PAGE_W, PAGE_H),)  # that build's pages, as a request and a snippet's answer carry them
# A second page of another size, as a landscape appendix or an \includepdf page leaves: 480 x 960 pt.
TALL_PX = (1000, 2000)
TALL_W, TALL_H = 480.0, 960.0
# One box per line of the manuscript's table (L12-L16), 16 pt apart - the leading the mark's padding is measured from.
TABLE_BOXES = {line: (1, 60.0, 100.0 + 16.0 * (line - 12), 300.0, 10.0) for line in range(12, 17)}
# A row added inside the tabular after the build read the file: its line is one no build ever read.
INSERTED = "cell deltaunique \\\\\nextra row epsilonrow \\\\"
# A manuscript whose ladder for L4 is three nested rungs: the line (4), its paragraph (4-5), the float (3-8).
NESTED = """\\documentclass{article}
\\begin{document}
\\begin{figure}
Alpha one uniquealpha.
Alpha two uniquebeta.

Beta three uniquegamma.
\\end{figure}
\\end{document}
"""


def frac(x, y, w, h, page_w=PAGE_W, page_h=PAGE_H):
    """A box in points as the answer gives it: page-relative [x, y, w, h] of a page_w x page_h page."""
    return [x / page_w, y / page_h, w / page_w, h / page_h]


def paragraph(rows):
    """A manuscript whose single paragraph holds `rows` lines of text, starting at line 4."""
    body = "".join("Row %d uniquerow%d.\n" % (i, i) for i in range(1, rows + 1))
    return "\\documentclass{article}\n\\begin{document}\n\n" + body + "\n\\end{document}\n"


class SnippetBase(Base):
    """The fixture manuscript with a build on screen whose one page is PAGE_PX, and a stub of the forward pass."""

    def setUp(self):
        """The page folder of the build on screen, with one page image to take the page size from and the record of
        the lines that build read - a snippet answers no mark without it (PinLocationService.snippet)."""
        super().setUp()
        self.D = ps.APP.docs[0]
        self.pages = self.D.dir / "pages"
        self.pages.mkdir(parents=True, exist_ok=True)
        (self.pages / "page-1.png").write_bytes(helpers_figure.png_header(*PAGE_PX))
        (self.pages / self.D.pdf_name).write_bytes(b"%PDF-1.4\n%%EOF\n")
        self.keep_built_source()
        self.calls = []

    def keep_built_source(self, text=TEX):
        """The build on screen kept main.tex as text, the way a LaTeX build publishes its source record."""
        record = built_source.encode({"main.tex": built_source.text_lines(text.encode("utf-8"))})
        (self.pages / built_source.SOURCE_NAME).write_text(record, encoding="utf-8")

    def write(self, text):
        """Replace the manuscript, leaving it newer than the build."""
        self.main.write_text(text, encoding="utf-8")

    def rebuilt(self, text):
        """Replace the manuscript and record it as the lines the build on screen read, as a fresh build leaves them:
        the file was not edited since, so a rung's range stands where that build's numbers put it."""
        self.write(text)
        self.keep_built_source(text)

    def built_tex(self):
        """The main file inside the build copy - the name the forward pass gives `synctex view -i`."""
        return str(self.D.build / "main.tex")

    def viewed(self, boxes=None):
        """A stub of synctex_view that records (file name, line) in self.calls and answers that line's box, if the
        test gave it one."""
        rows = {} if boxes is None else boxes

        def view(pdf, tex, line):
            """Record the call and answer the line's box."""
            self.calls.append((tex, line))
            row = rows.get(line)
            return [row] if row is not None else []

        return mock.patch.object(pick_source, "synctex_view", view)

    def snippet(self, query):
        """GET /api/snippet?<query> as the local agent: the parsed body of a 200."""
        code, _, out = split_resp(self.talk(req("GET", "/api/snippet?" + query)))
        self.assertEqual(code, 200, out)
        return json.loads(out)


class SnippetBoxes(SnippetBase):
    """GET /api/snippet?levels=1 on the manuscript's table: the ladder's rungs and the marks they carry."""

    def test_every_rung_carries_the_boxes_of_its_own_range(self):
        """The ladder of L14 is the cell's own line and the table around it: each rung's mark covers that rung's own
        lines, so the wider rung starts higher on the page and is taller. The single line is grown by a share of its
        height, the three by half the blank their 16 pt leading leaves. The table rung is one whole environment, so its
        own \\begin and \\end lines (L12, L16) are not asked and the mark covers the three lines between."""
        with self.viewed(TABLE_BOXES):
            body = self.snippet("file=main.tex&lo=14&hi=14&levels=1")
        self.assertEqual(
            [(lv["level"], lv["lo"], lv["hi"]) for lv in body["levels"]], [("para", 14, 14), ("env", 12, 16)]
        )
        self.assertEqual(
            [lv["boxes"] for lv in body["levels"]],
            [
                [{"page": 1, "frac": frac(58.25, 130.25, 303.5, 13.5)}],
                [{"page": 1, "frac": frac(57.0, 113.0, 306.0, 48.0)}],
            ],
        )
        self.assertEqual(sorted(line for _, line in self.calls), [13, 14, 15])

    def test_a_line_several_rungs_hold_is_read_once_for_the_whole_answer(self):
        """A ladder of three nested rungs - the dragged line, its paragraph, the float around it - holds L4 in all
        three and L5 in two: asked once per rung per line that would be 6 calls, each a process; every distinct line
        of text is asked for once instead, so the per-rung cap bounds the answer too. The float's own \\begin and
        \\end lines (L3, L8) are not asked. This route is what the viewer
        opens an edit card with."""
        self.rebuilt(NESTED)
        with self.viewed():
            body = self.snippet("file=main.tex&lo=4&hi=4&levels=1")
        rungs = [(lv["level"], lv["lo"], lv["hi"]) for lv in body["levels"]]
        self.assertEqual(rungs, [("raw", 4, 4), ("para", 4, 5), ("env", 3, 8)])
        self.assertEqual(self.calls, [(self.built_tex(), line) for line in (4, 5, 7)])

    def test_a_rung_has_no_boxes_when_the_forward_pass_is_silent(self):
        """A build whose .synctex.gz is gone or holds nothing for those lines: the key is absent from every rung,
        never an empty list, and the rest of the ladder stands."""
        with self.viewed():
            body = self.snippet("file=main.tex&lo=14&hi=14&levels=1")
        self.assertEqual([(lv["lo"], lv["hi"]) for lv in body["levels"]], [(14, 14), (12, 16)])
        self.assertEqual([lv for lv in body["levels"] if "boxes" in lv], [])

    def test_a_snippet_without_the_ladder_carries_no_boxes_and_asks_nothing(self):
        """Without levels=1 there is no rung to mark, and the viewer reads this route for every excerpt window: the
        answer is the lines alone and no process is run."""
        with self.viewed(TABLE_BOXES):
            body = self.snippet("file=main.tex&lo=14&hi=14")
        self.assertNotIn("levels", body)
        self.assertNotIn("boxes", body)
        self.assertEqual(self.calls, [])

    def test_a_rung_and_a_pick_answer_the_same_boxes_for_the_same_range(self):
        """The same file and the same lo..hi give the same mark through both paths: a drag traced to the table and the
        snippet of the lines that drag answered carry the same pieces (Review Focus 4)."""
        request = location_input.PickRequest(self.pages, 1, (10.0, 20.0, 150.0, 60.0), (PAGE_W, PAGE_H), None, PAGES)
        with self.viewed(TABLE_BOXES):
            with (
                mock.patch.object(pick_source, "by_synctex", return_value=(self.built_tex(), 14, 14)),
                mock.patch.object(pick_source, "region_text", return_value=""),
            ):
                picked = pick_resolve.pick(self.D, request, ps.APP.location_service.context())
            body = location_http.pick_answer(picked)
            rungs = self.snippet("file=main.tex&lo=%d&hi=%d&levels=1" % (body["lo"], body["hi"]))["levels"]
        default = next(lv for lv in body["levels"] if lv["level"] == body["default_level"])
        same_range = next(lv for lv in rungs if (lv["lo"], lv["hi"]) == (body["lo"], body["hi"]))
        self.assertEqual(same_range["boxes"], default["boxes"])
        self.assertEqual(default["boxes"], [{"page": 1, "frac": frac(57.0, 113.0, 306.0, 48.0)}])

    def test_a_rung_whose_range_moved_since_the_build_carries_no_boxes(self):
        """One row added inside the tabular after the build: the cell's own line still stands in the lines that build
        read and keeps its mark, while the rungs that now hold a line no build ever read get none - and nothing is
        asked for them. Everything else about those rungs is unchanged."""
        self.keep_built_source()
        self.write(TEX.replace("cell deltaunique \\\\", INSERTED, 1))
        with self.viewed(TABLE_BOXES):
            body = self.snippet("file=main.tex&lo=14&hi=14&levels=1")
        marked = [lv["level"] for lv in body["levels"] if "boxes" in lv]
        self.assertEqual(marked, ["raw"])
        wide = next(lv for lv in body["levels"] if lv["level"] == "env")
        self.assertEqual(sorted(wide), ["env", "hi", "label", "level", "lo", "n", "snippet"])
        self.assertEqual((wide["lo"], wide["hi"], wide["n"]), (12, 17, 6))
        self.assertEqual(self.calls, [(self.built_tex(), 14)])

    def test_no_rung_carries_boxes_on_a_build_that_kept_no_source_record(self):
        """A build made before Limn kept the lines it read: a request here carries only a file and a line range of
        the file as it is today, and with no record nothing says those numbers name the same lines in the build that
        drew the page on screen. Measuring them against that older layout would put the mark on text the range does
        not hold, so no rung carries one and no process is run - the same refusal the pin listing makes for such a
        build (ADR-0045 D7). A pick on the same build does answer, because SyncTeX gave it that build's own numbers
        (test_pick_boxes.py's test_a_build_without_a_source_record_gets_boxes_at_todays_lines)."""
        (self.pages / built_source.SOURCE_NAME).unlink()
        with self.viewed(TABLE_BOXES):
            body = self.snippet("file=main.tex&lo=14&hi=14&levels=1")
        self.assertEqual([(lv["lo"], lv["hi"]) for lv in body["levels"]], [(14, 14), (12, 16)])
        self.assertEqual([lv for lv in body["levels"] if "boxes" in lv], [])
        self.assertEqual(self.calls, [])

    def test_a_rung_over_the_line_cap_carries_no_boxes_and_asks_nothing(self):
        """A 45-line paragraph costs about 0.6 s of `synctex view`, so a rung over the cap of 40 lines answers no
        boxes without one call - while the dragged line beside it on the same ladder still gets its mark."""
        self.rebuilt(paragraph(45))
        with self.viewed({4: (1, 60.0, 100.0, 300.0, 10.0)}):
            body = self.snippet("file=main.tex&lo=4&hi=4&levels=1")
        self.assertEqual([(lv["level"], lv["lo"], lv["hi"]) for lv in body["levels"]], [("raw", 4, 4), ("para", 4, 48)])
        self.assertIn("boxes", body["levels"][0])
        self.assertNotIn("boxes", body["levels"][1])
        self.assertEqual(self.calls, [(self.built_tex(), 4)])

    def test_a_document_with_no_page_answers_the_snippet_it_always_did(self):
        """A build that left no page image: there is no page size to measure a mark against, so the route's answer is
        the ladder alone - field for field the one range.snippet_api gives without any build facts - and nothing is
        asked for."""
        (self.pages / "page-1.png").unlink()
        with self.viewed(TABLE_BOXES):
            body = self.snippet("file=main.tex&lo=14&hi=14&levels=1")
        rng = source_range.SourceRange(self.main, TEX.splitlines(), 14, 14)
        self.assertEqual(body, source_range.snippet_api(rng, True, ps.APP.C.envs))
        self.assertEqual(self.calls, [])

    def test_the_shared_computation_is_asked_with_the_builds_lines_before_todays(self):
        """boxes_for_range takes built before now: both are lines of the same file, so a swap would type-check and
        quietly answer the boxes of the wrong text. The build read the manuscript as it was; today's file has one row
        more, so the two are told apart by what they hold."""
        self.keep_built_source()
        self.write(TEX.replace("cell deltaunique \\\\", INSERTED, 1))
        asked = []

        def record(*args):
            """Keep the positional arguments of one call and answer no boxes."""
            asked.append(args)
            return ()

        with mock.patch.object(pick_source, "boxes_for_range", record):
            self.snippet("file=main.tex&lo=14&hi=14&levels=1")
        pdf, tex, built, now, lo, hi, pages, limit, _view = asked[0]
        self.assertEqual((pdf, tex), (self.pages / self.D.pdf_name, self.built_tex()))
        self.assertEqual((len(built), len(now)), (20, 21))
        self.assertNotIn("epsilonrow", "\n".join(built))
        self.assertIn("epsilonrow", "\n".join(now))
        self.assertEqual((lo, hi, tuple(pages), limit), (14, 14, PAGES, BOX_LIMIT))

    def test_the_default_provider_of_snippet_api_adds_nothing(self):
        """A caller with no build facts (the pure callers of range.snippet_api) answers exactly the ladder it did
        before: the default provider answers no pieces, so no rung grows a key."""
        rng = source_range.SourceRange(self.main, TEX.splitlines(), 14, 14)
        plain = source_range.snippet_api(rng, True, ps.APP.C.envs)
        self.assertEqual(plain, source_range.snippet_api(rng, True, ps.APP.C.envs, boxes=source_range.no_boxes))
        self.assertEqual([lv for lv in plain["levels"] if "boxes" in lv], [])


class MixedPageSizes(SnippetBase):
    """A build whose two pages are different sizes - a landscape appendix, an \\includepdf page - with the table's
    first three lines printing on page 1 and its last two on page 2."""

    # The range's boxes, 16 pt apart on each page: L12-L14 on page 1, L15-L16 on the narrower, taller page 2.
    SPLIT = {
        12: (1, 60.0, 100.0, 300.0, 10.0),
        13: (1, 60.0, 116.0, 300.0, 10.0),
        14: (1, 60.0, 132.0, 300.0, 10.0),
        15: (2, 80.0, 200.0, 200.0, 10.0),
        16: (2, 80.0, 216.0, 200.0, 10.0),
    }
    # What L13-L15 merge into (L12 and L16 are the environment's own \\begin and \\end, not asked): one piece per page,
    # each grown by the 3.0 pt padding the range's 16 pt leading gives.
    PIECES = [
        {"page": 1, "frac": frac(57.0, 113.0, 306.0, 32.0)},
        {"page": 2, "frac": frac(77.0, 197.0, 206.0, 16.0, TALL_W, TALL_H)},
    ]

    def setUp(self):
        """A second page image of another size beside the first."""
        super().setUp()
        (self.pages / "page-2.png").write_bytes(helpers_figure.png_header(*TALL_PX))

    def test_each_piece_of_a_mark_is_measured_against_its_own_page(self):
        """The piece on page 2 is divided by page 2's width and height: measured against page 1's it would be at
        0.107 x 0.410 of a page it is not on, and clipped to page 1's shorter box. The pieces come page by page, so
        the first is still the top of the range. The range is one whole environment, so L12 and L16, its own \\begin
        and \\end, are not asked: page 2 holds L15 alone, grown by the range's own 3.0 pt
        padding, which the 16 pt leading on page 1 gives (measured once over all the range's rows, not per page)."""
        with self.viewed(self.SPLIT):
            body = self.snippet("file=main.tex&lo=14&hi=14&levels=1")
        wide = next(lv for lv in body["levels"] if lv["level"] == "env")
        self.assertEqual(wide["boxes"], self.PIECES)
        self.assertNotEqual(self.PIECES[1]["frac"], frac(77.0, 197.0, 206.0, 16.0))  # not page 1's size

    def test_a_rung_and_a_pick_agree_on_a_document_whose_pages_differ(self):
        """A drag made on page 2 and the snippet of the lines it answered carry the same pieces, though the pick
        knows the page dragged on and the snippet knows none: both measure each piece against its own page."""
        pages = (PAGES[0], (TALL_W, TALL_H))
        request = location_input.PickRequest(self.pages, 2, (10.0, 20.0, 150.0, 60.0), (TALL_W, TALL_H), None, pages)
        with self.viewed(self.SPLIT):
            with (
                mock.patch.object(pick_source, "by_synctex", return_value=(self.built_tex(), 14, 14)),
                mock.patch.object(pick_source, "region_text", return_value=""),
            ):
                picked = pick_resolve.pick(self.D, request, ps.APP.location_service.context())
            body = location_http.pick_answer(picked)
            rungs = self.snippet("file=main.tex&lo=%d&hi=%d&levels=1" % (body["lo"], body["hi"]))["levels"]
        default = next(lv for lv in body["levels"] if lv["level"] == body["default_level"])
        same_range = next(lv for lv in rungs if (lv["lo"], lv["hi"]) == (body["lo"], body["hi"]))
        self.assertEqual(default["boxes"], self.PIECES)
        self.assertEqual(same_range["boxes"], default["boxes"])


class FigureSnippetBoxes(SnippetBase):
    """A figure document, whose ladder comes from its element map and whose lines are a drawing script's."""

    def test_a_figure_scripts_rung_carries_no_boxes(self):
        """The raw rung of a figure document is a line of Python, not a line of the manuscript, and a figure's marks
        come from its element map: the rung carries no boxes even though the forward pass would answer for any line."""
        fig = helpers_figure.figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), fig])
        self.addCleanup(ps.APP.set_docs, None)
        helpers_figure.write_build(fig, helpers_figure.BUILD1, helpers_figure.b2_map())
        with self.viewed({line: (1, 60.0, 100.0, 300.0, 10.0) for line in range(1, 141)}):
            body = self.snippet("doc=fig&file=%s&lo=88&hi=95&levels=1" % helpers_figure.SCRIPT)
        self.assertEqual([lv["level"] for lv in body["levels"]], ["raw"])
        self.assertNotIn("boxes", body["levels"][0])
        self.assertEqual(self.calls, [])

"""The boxes a pick's default level carries - a drag answered with the area its line range covers on the PDF
(docs/adr/0045-pin-marks-follow-the-range.md).

The forward pass runs `synctex view` once per line of the default level, so these tests stub
limn.pins.location.source.synctex_view and watch which lines and which file name it is asked for. That watching is the
point: the lines must be the ones that build read, the file must be the one inside that build's copy, and a line
without text must not be asked at all - the real tool answers a blank line through its ancestor search with the
printed lines of the paragraph before it (measured on a two-column 10 pt A4 document: 17 text boxes), which would draw
a mark over text the range does not hold.

Run: uv run pytest -q src/limn/pins/location/tests/test_pick_boxes.py
"""

from unittest import mock

from limn.builds import built_source
from limn.pins.location import (
    http as location_http,
    input as location_input,
    resolve as pick_resolve,
    source as pick_source,
)
from limn.runtime.documents import Doc

from helpers import TEX, Base, ps

# The page the drag is made on, and one line box per line of the range, whose fractions of that page are short decimals.
PAGE_W, PAGE_H = 600.0, 800.0
PAGES = ((PAGE_W, PAGE_H),)  # the build's one page, as the request carries every page's size
TWO_LINES = {8: (1, 60.0, 100.0, 300.0, 10.0), 9: (1, 60.0, 116.0, 300.0, 10.0)}
# What those two boxes become: joined, grown by the 3.0 pt padding their 16 pt leading gives, as page fractions.
ONE_PIECE = [{"page": 1, "frac": [0.095, 0.12125, 0.51, 0.04]}]

# A manuscript whose default level is a float environment holding a comment-only line and a blank line: the forward
# pass asks for the other four lines only.
FLOAT_TEX = """\\documentclass{article}
\\begin{document}
\\section{Intro}
\\begin{figure}
Alpha line one uniquealpha.
% a note inside the float

Beta line two uniquebeta.
\\end{figure}
\\end{document}
"""
# TEX line 8 with one line put above it inside the same paragraph - a line that build never read.
INSERTED = "Body line six inserted.\nBody line seven betaunique."


def float_with_rows(n: int) -> str:
    """A manuscript whose figure environment holds n rows of text, so its default level is n + 2 lines of text (the
    \\begin and \\end lines carry text too)."""
    rows = "".join("Row %d uniquerow%d.\n" % (i, i) for i in range(1, n + 1))
    return (
        "\\documentclass{article}\n\\begin{document}\n\\section{Intro}\n\\begin{figure}\n"
        + rows
        + "\\end{figure}\n\\end{document}\n"
    )


class PickBoxes(Base):
    """The fixture's document with a build on screen that read the manuscript, and a drag traced to its lines."""

    def setUp(self):
        """The page folder of the build on screen, older than the manuscript by a minute."""
        super().setUp()
        self.D = ps.APP.docs[0]
        self.pages = self.D.dir / "pages"
        self.pages.mkdir(parents=True, exist_ok=True)
        (self.D.dir / "built_src_mtime.txt").write_text("%f" % (self.main.stat().st_mtime - 60), encoding="utf-8")
        self.calls = []

    def keep_built_source(self, text=TEX):
        """The build on screen kept main.tex as text, the way a LaTeX build publishes its source record."""
        record = built_source.encode({"main.tex": built_source.text_lines(text.encode("utf-8"))})
        (self.pages / built_source.SOURCE_NAME).write_text(record, encoding="utf-8")

    def write(self, text):
        """Replace the manuscript, leaving it newer than the build."""
        self.main.write_text(text, encoding="utf-8")

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

    def picked(self, lo, hi, text=""):
        """pick for a box on page 1 of the build on screen, SyncTeX answering lines lo..hi of the build copy's
        main.tex and pdftotext printing text ("" - a region whose words decide nothing, so SyncTeX's range wins)."""
        request = location_input.PickRequest(self.pages, 1, (10.0, 20.0, 150.0, 60.0), (PAGE_W, PAGE_H), None, PAGES)
        with (
            mock.patch.object(pick_source, "by_synctex", return_value=(str(self.D.build / "main.tex"), lo, hi)),
            mock.patch.object(pick_source, "region_text", return_value=text),
        ):
            return pick_resolve.pick(self.D, request, ps.APP.location_service.context())

    def default_entry(self, body):
        """The one levels entry of a pick body that the body names its default level."""
        entries = [lv for lv in body["levels"] if lv["level"] == body["default_level"]]
        self.assertEqual(len(entries), 1, body["levels"])
        return entries[0]

    def test_a_pick_carries_the_boxes_of_its_default_level(self):
        """Two lines with a box each: the default level carries the one piece they merge into, as page fractions,
        and the range's own lines are what was asked for."""
        self.keep_built_source()
        with self.viewed(TWO_LINES):
            got = self.picked(8, 9)
        self.assertIsInstance(got, pick_resolve.Picked)
        body = location_http.pick_answer(got)
        self.assertEqual((body["lo"], body["hi"], body["default_level"]), (8, 9, "para"))
        self.assertEqual(self.default_entry(body)["boxes"], ONE_PIECE)
        self.assertEqual(self.calls, [(self.built_tex(), 8), (self.built_tex(), 9)])

    def test_a_pick_has_no_boxes_when_the_forward_pass_is_silent(self):
        """A build whose .synctex.gz is gone or holds nothing for those lines: the key is absent, never an empty
        list, and the rest of the answer stands."""
        self.keep_built_source()
        with self.viewed():
            got = self.picked(8, 9)
        body = location_http.pick_answer(got)
        self.assertNotIn("boxes", self.default_entry(body))
        self.assertEqual((body["lo"], body["hi"], body["via"]), (8, 9, "synctex"))

    def test_a_pick_still_answers_when_synctex_view_fails(self):
        """The real synctex_view with no `synctex` on PATH: it answers nothing, and every other key of the pick is
        what it was before there were boxes."""
        self.keep_built_source()

        def missing(*args, **kwargs):
            """subprocess.run as it fails when the tool is not installed."""
            raise FileNotFoundError

        with mock.patch.object(pick_source.subprocess, "run", missing):
            got = self.picked(8, 9)
        body = location_http.pick_answer(got)
        self.assertEqual((body["lo"], body["hi"], body["via"], body["warn"]), (8, 9, "synctex", ""))
        self.assertIn("betaunique", body["snippet"])
        self.assertNotIn("boxes", self.default_entry(body))

    def test_a_range_whose_text_moved_since_the_build_gets_no_boxes(self):
        """One line put into the paragraph after the build: the default level holds a line that build never read, so
        the range as a whole has no place on that PDF and gets no box - and nothing is asked for."""
        self.keep_built_source()
        self.write(TEX.replace("Body line seven betaunique.", INSERTED, 1))
        with self.viewed(TWO_LINES):
            got = self.picked(8, 9)
        body = location_http.pick_answer(got)
        self.assertEqual((body["lo"], body["hi"], body["warn"]), (8, 10, ""))
        self.assertNotIn("boxes", self.default_entry(body))
        self.assertEqual(self.calls, [])

    def test_a_build_without_a_source_record_gets_boxes_at_todays_lines(self):
        """A build made before builds kept their source: there is nothing to read the range back into, so the lines
        are taken as they are now - the numbers SyncTeX's own answer already stands for."""
        with self.viewed(TWO_LINES):
            got = self.picked(8, 9)
        body = location_http.pick_answer(got)
        self.assertEqual(self.default_entry(body)["boxes"], ONE_PIECE)
        self.assertEqual(self.calls, [(self.built_tex(), 8), (self.built_tex(), 9)])

    def test_the_forward_pass_skips_blank_and_comment_only_lines_of_the_range(self):
        """The default level is a figure environment of six lines. Its own \\begin and \\end lines are not asked (the
        range is one whole environment) and two more hold no text once the comment is stripped: only the two rows
        between are asked for, each by the main file's name inside the build copy."""
        self.write(FLOAT_TEX)
        self.keep_built_source(FLOAT_TEX)
        with self.viewed():
            got = self.picked(5, 5)
        body = location_http.pick_answer(got)
        self.assertEqual((body["lo"], body["hi"], body["default_level"]), (4, 9, "env"))
        self.assertEqual(self.calls, [(self.built_tex(), line) for line in (5, 8)])

    def test_a_range_over_the_line_cap_asks_for_nothing(self):
        """41 lines asked cost about half a second of `synctex view` on a 35-page document, and the pick sits on
        the drag's path: over the cap of 40 it answers no boxes without one call. At the cap it still asks. The cap
        counts the lines asked, so the float's own \\begin and \\end lines, which are not asked, do not count."""
        for rows, calls in ((41, 0), (40, 40)):
            with self.subTest(rows=rows):
                self.calls = []
                text = float_with_rows(rows)
                self.write(text)
                self.keep_built_source(text)
                with self.viewed():
                    got = self.picked(6, 6)
                body = location_http.pick_answer(got)
                self.assertEqual(body["default_level"], "env")
                self.assertEqual(len(self.calls), calls)
                self.assertNotIn("boxes", self.default_entry(body))

    def test_the_boxes_go_on_the_default_level_alone_and_the_traced_ladder_is_untouched(self):
        """The body's other rungs carry no boxes, and the Traced the resolver answered is left as it was - the body
        holds a copy of the default rung, so another reader of traced.levels sees no boxes."""
        self.write(FLOAT_TEX)
        self.keep_built_source(FLOAT_TEX)
        with self.viewed({4: (1, 60.0, 100.0, 300.0, 10.0), 5: (1, 60.0, 116.0, 300.0, 10.0)}):
            got = self.picked(5, 5)
        body = location_http.pick_answer(got)
        self.assertIn("boxes", self.default_entry(body))
        self.assertEqual([lv["level"] for lv in body["levels"] if "boxes" in lv], ["env"])
        self.assertEqual([lv["level"] for lv in got.traced.levels if "boxes" in lv], [])


class PickOutsideTheBuildRoot(Base):
    """A document whose build root is one folder of the manuscript, picked on a file outside that folder."""

    def test_a_file_outside_the_build_root_is_asked_for_by_its_checkout_path(self):
        """The build copy holds what lies below the build root, so a file beside it has no name inside the copy: the
        forward pass falls back to the checkout path instead of failing the pick."""
        paper = self.src / "paper"
        paper.mkdir()
        (paper / "main.tex").write_text(TEX, encoding="utf-8")
        shared = self.src / "shared.tex"
        shared.write_text(TEX, encoding="utf-8")
        D = Doc("paper", "본문", "tex", paper, paper / "main.tex", paths=ps.APP.C.paths)
        ps.APP.set_docs([D])
        self.addCleanup(ps.APP.set_docs, None)
        (D.dir / "pages").mkdir(parents=True)
        calls = []

        def view(pdf, tex, line):
            """Record the call; the boxes do not matter here."""
            calls.append((tex, line))
            return []

        request = location_input.PickRequest(
            D.dir / "pages", 1, (10.0, 20.0, 150.0, 60.0), (PAGE_W, PAGE_H), None, PAGES
        )
        with (
            mock.patch.object(pick_source, "by_synctex", return_value=(str(shared), 8, 9)),
            mock.patch.object(pick_source, "region_text", return_value=""),
            mock.patch.object(pick_source, "synctex_view", view),
        ):
            got = pick_resolve.pick(D, request, ps.APP.location_service.context())
        self.assertIsInstance(got, pick_resolve.Picked)
        self.assertEqual(got.file, shared)
        self.assertEqual(calls, [(str(shared), 8), (str(shared), 9)])

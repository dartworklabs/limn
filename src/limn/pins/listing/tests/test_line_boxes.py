"""The `boxes` a stored LaTeX line pin carries in GET /api/pins - where its lines print on the build on screen
(docs/adr/0045-pin-marks-follow-the-range.md).

A pin's mark is the area its line range covers, so the marks already on the page are drawn the way a fresh pick and a
snippet draw them. The field is computed on every read and never stored, like `rel`, `est`, `mark` and `state`, and
it is add-only: a client that does not know it reads the answer it always read. The forward pass runs `synctex view`
once per line of text, so these tests stub limn.pins.location.source.synctex_view and watch which lines it is asked
for - a listing that asks for a figure's element pin, a region pin or a document with no line pins at all would cost
one process per line for nothing.

Run: uv run pytest -q src/limn/pins/listing/tests/test_line_boxes.py
"""

import json
from unittest import mock

from limn.builds import built_source
from limn.pins.location import source as pick_source
from limn.runtime.documents import Doc
from limn.security.access import LOCAL_ACTOR

import helpers_figure
from helpers import MINI_PDF, TEX, Base, add_pin, ps, req, split_resp
from helpers_access import ALICE_ACTOR, BOB_ACTOR
from helpers_figure import AUGUST_BOX, BUILD1, JULY_BOX, SCRIPT, b2_map, figure_doc, pin_from_pick, write_build

PAGE_PX = (1500, 1000)  # the page image the build on screen left
PAGE_W, PAGE_H = 720.0, 480.0  # its size in points at the fixture's 150 dpi
# One box per line of the manuscript's table (L12-L16), 16 pt apart - the leading the mark's padding is measured from.
TABLE_BOXES = {line: (1, 60.0, 100.0 + 16.0 * (line - 12), 300.0, 10.0) for line in range(12, 17)}
# The mark the three lines between the table's own \\begin and \\end (L13-L15) merge into: one piece, grown by half the
# 3 pt blank their leading leaves. L12 and L16 are the range's own delimiters and are not asked.
TABLE_MARK = [{"page": 1, "frac": [57.0 / PAGE_W, 113.0 / PAGE_H, 306.0 / PAGE_W, 48.0 / PAGE_H]}]
# A row added inside the tabular after the build read the file: its line is one no build ever read.
INSERTED = "cell deltaunique \\\\\nextra row epsilonrow \\\\"


class ListingBase(Base):
    """The fixture manuscript with a build on screen whose one page is PAGE_PX, and a stub of the forward pass."""

    def setUp(self):
        """The page folder of the build on screen, with one page image to take the page size from."""
        super().setUp()
        self.D = ps.APP.docs[0]
        self.pages = self.D.dir / "pages"
        self.pages.mkdir(parents=True, exist_ok=True)
        (self.pages / "page-1.png").write_bytes(helpers_figure.png_header(*PAGE_PX))
        (self.pages / self.D.pdf_name).write_bytes(b"%PDF-1.4\n%%EOF\n")
        self.calls = []

    def keep_built_source(self, text=TEX):
        """The build on screen kept main.tex as text, the way a LaTeX build publishes its source record."""
        record = built_source.encode({"main.tex": built_source.text_lines(text.encode("utf-8"))})
        (self.pages / built_source.SOURCE_NAME).write_text(record, encoding="utf-8")

    def write(self, text):
        """Replace the manuscript, leaving it newer than the build."""
        self.main.write_text(text, encoding="utf-8")

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

    def listed(self, query="?all=1"):
        """GET /api/pins through the handler, by pin id."""
        code, _, body = split_resp(self.talk(req("GET", "/api/pins" + query)))
        self.assertEqual(code, 200, body)
        return {p["id"]: p for p in json.loads(body)}

    def stored(self):
        """The records in pins.jsonl as they are written, by pin id."""
        lines = ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines()
        return {r["id"]: r for r in (json.loads(line) for line in lines if line.strip())}


class ListedLineBoxes(ListingBase):
    """A LaTeX line pin on the build on screen: the mark its own lines draw."""

    def test_a_listed_line_pin_carries_the_boxes_of_its_range(self):
        """The pin holds the table's five lines, so its mark is the one block the three between its own \\begin and
        \\end merge into - the same pieces the same lines answer through a pick and through a snippet."""
        self.keep_built_source()
        pid = self.add(12, 16)
        with self.viewed(TABLE_BOXES):
            pin = self.listed()[pid]
        self.assertEqual(pin["boxes"], TABLE_MARK)
        self.assertEqual(sorted(line for _, line in self.calls), [13, 14, 15])

    def test_the_boxes_follow_the_fields_the_answer_always_had(self):
        """boxes is add-only: every field of the answer before it is there, in its order, and boxes comes after them."""
        self.keep_built_source()
        pid = self.add(12, 16)
        with self.viewed():
            plain = self.listed()[pid]
        with self.viewed(TABLE_BOXES):
            marked = self.listed()[pid]
        self.assertNotIn("boxes", plain)
        self.assertEqual([k for k in marked if k != "boxes"], list(plain))

    def test_boxes_are_not_written_to_the_record(self):
        """The field is computed on every read: a listing that answers it leaves pins.jsonl as it was, and a client
        that sends `boxes` with a new pin has it discarded like any field the store does not keep."""
        self.keep_built_source()
        pid = add_pin(
            {"file": str(self.main), "lo": 12, "hi": 16, "page": 1, "note": "n", "boxes": [{"page": 1, "frac": []}]},
            dict(LOCAL_ACTOR),
        ).core.pid
        before = ps.APP.C.pins_jsonl.read_bytes()
        with self.viewed(TABLE_BOXES):
            self.assertEqual(self.listed()[pid]["boxes"], TABLE_MARK)
        self.assertNotIn("boxes", self.stored()[pid])
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)

    def test_one_pin_read_on_its_own_carries_the_same_boxes(self):
        """GET /api/pins/<id> renders one pin through the same list, so the mark does not depend on the route."""
        self.keep_built_source()
        pid = self.add(12, 16)
        with self.viewed(TABLE_BOXES):
            code, _, body = split_resp(self.talk(req("GET", "/api/pins/%d" % pid)))
        self.assertEqual(code, 200, body)
        self.assertEqual(json.loads(body)["pin"]["boxes"], TABLE_MARK)

    def test_no_boxes_when_the_range_no_longer_stands(self):
        """One row added inside the tabular after the build: the pin's lines now hold a line no build ever read, so
        half the range's boxes are not passed off as the range's - the key is absent and nothing is asked for."""
        self.keep_built_source()
        self.write(TEX.replace("cell deltaunique \\\\", INSERTED, 1))
        pid = self.add(12, 16)
        with self.viewed(TABLE_BOXES):
            pin = self.listed()[pid]
        self.assertNotIn("boxes", pin)
        self.assertEqual(self.calls, [])

    def test_a_build_that_kept_no_source_record_answers_no_boxes(self):
        """A build of an older Limn published no record of the lines it read, so the listing cannot tell whether the
        pin's range still stands on them. A pick there falls back to the build's numbers as they are; a stored pin
        does not - such a build is replaced by the next rebuild (spec D7)."""
        pid = self.add(12, 16)
        with self.viewed(TABLE_BOXES):
            pin = self.listed()[pid]
        self.assertNotIn("boxes", pin)
        self.assertEqual(self.calls, [])

    def test_a_document_with_no_page_answers_no_boxes_and_asks_nothing(self):
        """A build that left no page image: there is no page size to measure a mark against, so the answer is the one
        the listing gave before marks followed the range."""
        self.keep_built_source()
        (self.pages / "page-1.png").unlink()
        pid = self.add(12, 16)
        with self.viewed(TABLE_BOXES):
            pin = self.listed()[pid]
        self.assertNotIn("boxes", pin)
        self.assertEqual(self.calls, [])

    def test_the_forward_pass_is_silent_for_the_range(self):
        """A build whose .synctex.gz holds nothing for those lines: the key is absent, never an empty list."""
        self.keep_built_source()
        pid = self.add(12, 16)
        with self.viewed():
            pin = self.listed()[pid]
        self.assertNotIn("boxes", pin)


class CachedAcrossRequests(ListingBase):
    """The run keeps the answers it has computed: the viewer polls GET /api/pins, and a listing that ran the forward
    pass again for every poll would hold up every other GET in the process."""

    def test_the_second_request_for_the_same_build_and_range_runs_synctex_once(self):
        """Two listings of the same pin on the same build: the three lines are asked for once, not six times."""
        self.keep_built_source()
        pid = self.add(12, 16)
        with self.viewed(TABLE_BOXES):
            first = self.listed()[pid]
            second = self.listed()[pid]
        self.assertEqual(second["boxes"], TABLE_MARK)
        self.assertEqual(second["boxes"], first["boxes"])
        self.assertEqual(sorted(line for _, line in self.calls), [13, 14, 15])

    def test_a_new_build_identity_misses_the_cache(self):
        """A rebuild publishes new pages and a new PDF, so the answer of the build before it says nothing about where
        the lines print now: the range is asked for again."""
        self.keep_built_source()
        pid = self.add(12, 16)
        with self.viewed(TABLE_BOXES):
            self.listed()
            self.calls.clear()
            after = self.D.dir / "pages-20260926110000"
            after.mkdir(parents=True)
            for name in ("page-1.png", self.D.pdf_name, built_source.SOURCE_NAME):
                (after / name).write_bytes((self.pages / name).read_bytes())
            (self.D.dir / "pages.cur").write_text(after.name, encoding="utf-8")
            pin = self.listed()[pid]
        self.assertEqual(pin["boxes"], TABLE_MARK)
        self.assertEqual(sorted(line for _, line in self.calls), [13, 14, 15])

    def test_an_edited_manuscript_misses_the_cache(self):
        """The answer depends on the file's text as well as the build's: a file written again is a new question, and
        a range that no longer stands whole in it loses its mark instead of keeping the one it had."""
        self.keep_built_source()
        pid = self.add(12, 16)
        with self.viewed(TABLE_BOXES):
            self.assertEqual(self.listed()[pid]["boxes"], TABLE_MARK)
            self.write(TEX.replace("cell deltaunique \\\\", INSERTED, 1))
            pin = self.listed()[pid]
        self.assertNotIn("boxes", pin)


class OtherPinsOnTheList(ListingBase):
    """What the pins that are not LaTeX line pins keep: a figure document's element pin, a region pin on a view-only
    PDF, and a listing with none of a manuscript's lines on it."""

    def setUp(self):
        """A LaTeX document ms, a figure document fig with BUILD1 on screen, and a view-only PDF rv with a page."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        (self.src / "review.pdf").write_bytes(MINI_PDF)
        self.rv = Doc("rv", "리뷰어", "pdf", self.src, self.src / "review.pdf", paths=ps.APP.C.paths)
        self.ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        ps.APP.set_docs([self.ms, self.fig, self.rv])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())
        write_build(self.rv, BUILD1, None)

    def test_a_figure_pin_keeps_its_element_marks_and_gains_no_boxes(self):
        """A figure's mark comes from its element map, not from SyncTeX: the element pin still carries mark, mark_page
        and el_sync, and no line of its drawing script is asked for."""
        july = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "글자를 키워 줘")
        with self.viewed({line: (1, 60.0, 100.0, 300.0, 10.0) for line in range(1, 141)}):
            pin = self.listed()[july]
        self.assertEqual([k for k in ("mark", "mark_page", "el_sync") if k in pin], ["mark", "mark_page", "el_sync"])
        self.assertNotIn("boxes", pin)
        self.assertEqual(self.calls, [])

    def test_a_figure_line_pin_without_an_element_gains_nothing_either(self):
        """A pin on the lines of the drawing script: those lines are Python, not a manuscript a LaTeX build printed."""
        plain = add_pin(
            {"doc": "fig", "file": SCRIPT, "lo": 20, "hi": 22, "note": "선 굵기"}, dict(LOCAL_ACTOR)
        ).core.pid
        with self.viewed({line: (1, 60.0, 100.0, 300.0, 10.0) for line in range(1, 141)}):
            pin = self.listed()[plain]
        self.assertNotIn("boxes", pin)
        self.assertEqual(self.calls, [])

    def test_a_region_pin_gets_neither_an_element_mark_nor_boxes(self):
        """A region of a view-only PDF is the whole location: it has no line range to draw and no element to follow."""
        region = add_pin(
            {"doc": "rv", "page": 1, "frac": [0.1, 0.2, 0.3, 0.4], "pdf_build": BUILD1, "note": "여기"},
            dict(BOB_ACTOR),
        ).core.pid
        with self.viewed(TABLE_BOXES):
            pin = self.listed()[region]
        self.assertEqual([k for k in ("boxes", "mark", "mark_page", "el_sync") if k in pin], [])
        self.assertEqual(self.calls, [])

    def test_a_listing_without_a_latex_line_pin_runs_synctex_zero_times(self):
        """An element pin, a figure script's lines and a region make the whole list: the forward pass is a process per
        line, and GET /api/pins answers every open pin of every document at once."""
        pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "글자를 키워 줘")
        pin_from_pick(self.fig, AUGUST_BOX, BOB_ACTOR, "색을 바꿔 줘")
        add_pin({"doc": "fig", "file": SCRIPT, "lo": 20, "hi": 22, "note": "선 굵기"}, dict(LOCAL_ACTOR))
        add_pin({"doc": "rv", "page": 1, "frac": [0, 0, 1, 1], "pdf_build": BUILD1, "note": "여기"}, dict(BOB_ACTOR))
        with self.viewed(TABLE_BOXES):
            listed = self.listed()
        self.assertEqual(len(listed), 4)
        self.assertEqual([p["id"] for p in listed.values() if "boxes" in p], [])
        self.assertEqual(self.calls, [])

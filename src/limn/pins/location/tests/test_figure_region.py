"""Picking and pinning on a figure document (docs/handbook/api.md §보기 전용 PDF 문서의 pick·핀): until the map drives
the pick, a figure document answers the view-only region body, named after the PDF its build's map names.

The page directory is made by hand the way an import leaves it (a page image, the PDF copy and the map copy), so no
renderer runs; pdftotext is replaced by a stand-in that records which PDF it was asked to read.

Run: uv run pytest -q src/limn/pins/location/tests/test_figure_region.py
"""

import json
from pathlib import Path
from unittest import mock

from limn.administration import serve_documents as startup_documents
from limn.builds import artifacts as limn_build
from limn.pins.location import source as pick_source
from limn.platform import files as files

from helpers import MINI_PDF, Base, blank_png, figure_map, fits, jreq, map_bytes, ps, split_resp

DRAG = {"doc": "fig", "page": 1, "x0": 10, "y0": 10, "x1": 40, "y1": 30}


class FigureRegionPick(Base):
    """Documents ms (the fixture body) and fig (folder figs/, map figs/out/figures.limnmap.json) with one imported
    build on screen."""

    def setUp(self):
        """The figure files, the two documents, and build pages-20260101000000 of fig on screen."""
        super().setUp()
        self.figs = self.src / "figs"
        (self.figs / "out").mkdir(parents=True)
        (self.figs / "out" / "figures.pdf").write_bytes(MINI_PDF)
        (self.figs / "out" / "figures.limnmap.json").write_bytes(map_bytes(figure_map(MINI_PDF)))
        docs = startup_documents.make_docs(
            ["ms=본문:main.tex", "fig=그림:figs::out/figures.limnmap.json"], self.src, ps.APP.C.paths
        )
        ps.APP.set_docs(docs)
        self.fig = docs[1]
        self.pdir = self.publish("pages-20260101000000", figure_map(MINI_PDF))

    def tearDown(self):
        """Back to the single document before the fixture removes the manuscript."""
        ps.APP.set_docs(None)
        super().tearDown()

    def publish(self, name: str, m: dict) -> Path:
        """Page directory `name` of fig as an import leaves it - one 200x200 page, the PDF copy and map m - put on
        screen."""
        d = self.fig.dir / name
        d.mkdir(parents=True)
        (d / "page-1.png").write_bytes(blank_png(200, 200))
        (d / self.fig.pdf_name).write_bytes(MINI_PDF)
        (d / limn_build.FIGMAP_NAME).write_bytes(map_bytes(m))
        files.atomic_write(self.fig.dir / "pages.cur", name)
        return d

    def pick(self, body: dict) -> dict:
        """POST /api/pick with body, pdftotext answering nothing; the 200 body."""
        with mock.patch.object(pick_source, "region_text", return_value=""):
            code, _, raw = split_resp(self.talk(jreq("POST", "/api/pick", body)))
        self.assertEqual(code, 200, raw)
        return json.loads(raw)

    def test_a_figure_pick_answers_a_region_named_after_the_maps_pdf(self):
        """The region body of a view-only PDF, with pdf and name taken from the build's map; the region's text is read
        from that build's PDF copy, and SyncTeX is never asked."""
        with (
            mock.patch.object(pick_source, "region_text", return_value="July") as text,
            mock.patch.object(pick_source, "by_synctex", side_effect=AssertionError("no SyncTeX for a figure")),
        ):
            code, _, raw = split_resp(self.talk(jreq("POST", "/api/pick", DRAG)))
        d = json.loads(raw)
        self.assertEqual(code, 200)
        self.assertEqual(
            (d["kind"], d["view_only"], d["pdf"], d["name"], d["quote"], d["pdf_build"]),
            ("region", True, "figs/out/figures.pdf", "figures.pdf", "July", self.pdir.name),
        )
        self.assertEqual(text.call_args.args[0], self.pdir / "figures.pdf")

    def test_a_pick_on_an_older_build_names_that_builds_pdf(self):
        """A drag made on the previous build is named after that build's map, not the one on screen."""
        old = self.publish("pages-20251231000000", figure_map(MINI_PDF, "older.pdf"))
        files.atomic_write(self.fig.dir / "pages.cur", self.pdir.name)
        d = self.pick(dict(DRAG, pdf_build=old.name))
        self.assertEqual((d["pdf"], d["name"], d["pdf_build"]), ("figs/out/older.pdf", "older.pdf", old.name))

    def test_a_map_copy_that_is_missing_or_names_a_pdf_outside_names_the_map_file(self):
        """Without a loadable map, or with one whose pdf escapes the document folder, the region names the map file -
        never a path outside (docs/handbook/code-style-roadmap.md §R10)."""
        copy = self.pdir / limn_build.FIGMAP_NAME
        for m in (None, figure_map(MINI_PDF, "../../../outside.pdf")):
            with self.subTest(pdf=m and m["pdf"]):
                copy.unlink(missing_ok=True)
                if m is not None:
                    copy.write_bytes(map_bytes(m))
                d = self.pick(DRAG)
                self.assertEqual((d["pdf"], d["name"]), ("figs/out/figures.limnmap.json", "figures.limnmap.json"))

    def test_a_region_pin_on_a_figure_document_records_the_maps_pdf(self):
        """POST /api/pin stores a region pin whose pdf is the absolute path of the PDF the map on screen names."""
        body = {"doc": "fig", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "7월 글자", "quote": "July"}
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        self.assertEqual(code, 200, raw)
        rec = self.pin(json.loads(raw)["id"])
        self.assertEqual(
            (rec["doc"], rec["kind"], rec["pdf"], rec["name"]),
            ("fig", "region", str((self.figs / "out" / "figures.pdf").resolve()), "figures.pdf"),
        )
        self.assertNotIn("file", rec)
        self.assertTrue(fits(rec))

    def test_a_figure_document_takes_no_line_pin(self):
        """A line pin on a figure document is refused as on a view-only PDF (400 no_source_lines)."""
        body = {"doc": "fig", "file": "figs/src/B2_calendar.py", "lo": 1, "hi": 2, "page": 1}
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        self.assertEqual((code, json.loads(raw)["reason"]), (400, "no_source_lines"))

    def test_a_file_only_pin_under_the_figure_folder_goes_to_the_latex_document(self):
        """The figure folder lies inside the body's build root: an agent's pin that names only a file there becomes a
        line pin of the LaTeX document, never of the figure."""
        (self.figs / "src").mkdir()
        (self.figs / "src" / "B2_calendar.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        body = {"file": "figs/src/B2_calendar.py", "lo": 1, "hi": 2}
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        self.assertEqual(code, 200, raw)
        self.assertEqual(self.pin(json.loads(raw)["id"])["doc"], "ms")

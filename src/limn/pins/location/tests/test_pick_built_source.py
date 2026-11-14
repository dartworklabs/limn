"""A pick on a build whose source was edited since answers where the dragged text stands now
(docs/handbook/domain.md §역매핑, docs/handbook/build-sync.md §빌드가 읽은 원고 줄).

SyncTeX of a build numbers the lines of the source that build read. The build keeps those lines (its source record), and
the pick carries SyncTeX's range over to the file as it is today before anything else uses it. The first class stubs
SyncTeX and pdftotext at the module's two subprocess functions and writes the record the way a build does; the second
runs a real build and asks over the pick's HTTP entry.

Run: uv run pytest -q src/limn/pins/location/tests/test_pick_built_source.py
"""

import os
from unittest import mock

from limn.builds import artifacts as limn_build, built_source, holds
from limn.builds.artifacts import BuildOk
from limn.pins.location import (
    http as location_http,
    input as location_input,
    resolve as pick_resolve,
    source as pick_source,
)

from helpers import TEX, Base, needs_tex, pick, ps

BODY = ["Body line seven betaunique.", "Body line eight gammaunique."]  # lines 8-9 of TEX
ADDED = "\\section{Intro}\nAdded one.\n\nAdded two.\nAdded three.\n\n"  # five lines more than the heading alone
STALE = location_http.PICK_WARNINGS["stale"]


class PickAfterAnEdit(Base):
    """The fixture's document with a build on screen that read TEX, and a manuscript edited since."""

    def setUp(self):
        """The page folder of the build on screen, older than the manuscript by a minute."""
        super().setUp()
        self.D = ps.APP.docs[0]
        self.pages = self.D.dir / "pages"
        self.pages.mkdir(parents=True, exist_ok=True)
        (self.D.dir / "built_src_mtime.txt").write_text("%f" % (self.main.stat().st_mtime - 60), encoding="utf-8")

    def keep_built_source(self, text=TEX):
        """The build on screen kept main.tex as text, the way a LaTeX build publishes its source record."""
        record = built_source.encode({"main.tex": built_source.text_lines(text.encode("utf-8"))})
        (self.pages / built_source.SOURCE_NAME).write_text(record, encoding="utf-8")

    def edit(self, old, new):
        """Replace old by new in the manuscript, once, leaving it newer than the build."""
        text = self.main.read_text(encoding="utf-8")
        self.assertIn(old, text)
        self.main.write_text(text.replace(old, new, 1), encoding="utf-8")

    def pick(self, lo, hi, text=""):
        """pick for a box on page 1 of the build on screen, SyncTeX answering lines lo..hi of the build copy's main.tex
        and pdftotext printing text ("" - a region whose words decide nothing, so SyncTeX's range is the answer)."""
        request = location_input.PickRequest(self.pages, 1, (10.0, 20.0, 150.0, 60.0), (600.0, 800.0), None)
        with (
            mock.patch.object(pick_source, "by_synctex", return_value=(str(self.D.build / "main.tex"), lo, hi)),
            mock.patch.object(pick_source, "region_text", return_value=text),
        ):
            return pick_resolve.pick(self.D, request, ps.APP.location_service.context())

    def lines_of(self, picked):
        """The raw lines of a traced answer, read from the manuscript as it is now."""
        now = self.main.read_text(encoding="utf-8").splitlines()
        return now[picked.traced.raw_lo - 1 : picked.traced.raw_hi]

    def test_lines_added_above_since_the_build_leave_the_answer_on_the_dragged_text(self):
        """Five lines added above the paragraph after the build: SyncTeX still says 8-9, the answer is 13-14, the same
        two lines, and it carries no stale sentence - a rebuild and a second pick would answer these lines."""
        self.keep_built_source()
        self.edit("\\section{Intro}\n", ADDED)
        got = self.pick(8, 9)
        self.assertIsInstance(got, pick_resolve.Picked)
        self.assertEqual((got.traced.via, got.traced.raw_lo, got.traced.raw_hi), ("synctex", 13, 14))
        self.assertEqual(self.lines_of(got), BODY)
        self.assertEqual(got.n_lines, len(TEX.splitlines()) + 5)
        self.assertIn("betaunique", got.snippet)
        self.assertEqual(location_http.pick_answer(got)["warn"], "")

    def test_lines_removed_above_since_the_build_leave_the_answer_on_the_dragged_text(self):
        """The first paragraph removed after the build: the answer moves up with its text."""
        self.keep_built_source()
        self.edit("First paragraph line one about rarewordalpha.\nFirst paragraph line two.\n\n", "")
        got = self.pick(8, 9, " ".join(BODY))
        self.assertIsInstance(got, pick_resolve.Picked)
        self.assertEqual((got.traced.via, got.traced.raw_lo, got.traced.raw_hi), ("synctex", 5, 6))
        self.assertEqual(self.lines_of(got), BODY)

    def test_an_unchanged_file_under_a_newer_manuscript_is_answered_without_the_stale_sentence(self):
        """The manuscript's clock is newer than the build and this file is as the build read it: the lines are the
        build's own, so nothing asks for a rebuild."""
        self.keep_built_source()
        got = self.pick(8, 9)
        self.assertEqual((got.traced.raw_lo, got.traced.raw_hi), (8, 9))
        self.assertEqual(location_http.pick_answer(got)["warn"], "")

    def test_a_line_rewritten_inside_the_range_keeps_the_stale_sentence(self):
        """One of the two dragged lines rewritten: the answer spans where the range stands, and still says the PDF is
        older than the manuscript - the text on screen is no longer the text in those lines."""
        self.keep_built_source()
        self.edit("\\section{Intro}\n", ADDED)
        self.edit(BODY[1], "Body line eight, reworded.")
        got = self.pick(8, 9)
        self.assertIsInstance(got, pick_resolve.Picked)
        self.assertEqual((got.traced.raw_lo, got.traced.raw_hi), (13, 13))
        self.assertEqual(self.lines_of(got), BODY[:1])
        self.assertEqual(location_http.pick_answer(got)["warn"], STALE)

    def test_text_deleted_since_the_build_is_refused_not_answered_at_its_old_numbers(self):
        """The dragged paragraph deleted after the build: lines 8-9 now hold other text, and the answer is the
        refusal - with the region's words too, which are in no line any more."""
        self.keep_built_source()
        self.edit("\n".join(BODY) + "\n", "")
        self.assertEqual(self.pick(8, 9), pick_resolve.NoSourceHere())
        self.assertEqual(self.pick(8, 9, " ".join(BODY)), pick_resolve.NoSourceHere())
        self.assertEqual(
            location_http.pick_answer(self.pick(8, 9))["reason"],
            "no_source_here",
        )

    def test_text_moved_out_of_reach_of_the_diff_is_found_by_its_words(self):
        """The paragraph cut and pasted to the end of the document: the line diff no longer pairs it, so SyncTeX has
        no range, and the region's words find it where it stands - with the stale sentence, as the text path alone
        answered."""
        self.keep_built_source()
        self.edit("\n".join(BODY) + "\n", "")
        self.edit("Tail paragraph zetaunique.\n", "Tail paragraph zetaunique.\n\n" + "\n".join(BODY) + "\n")
        got = self.pick(8, 9, " ".join(BODY))
        self.assertIsInstance(got, pick_resolve.Picked)
        self.assertEqual(got.traced.via, "text")
        self.assertEqual(self.lines_of(got), BODY)
        self.assertEqual(location_http.pick_answer(got)["warn"], STALE)

    def test_a_build_without_the_record_is_answered_with_synctex_s_numbers_and_the_stale_sentence(self):
        """A build made before builds kept their source: the answer is SyncTeX's lines as they are, and the stale
        sentence says they may be off."""
        self.edit("\\section{Intro}\n", ADDED)
        got = self.pick(8, 9)
        self.assertIsInstance(got, pick_resolve.Picked)
        self.assertEqual((got.traced.via, got.traced.raw_lo, got.traced.raw_hi), ("synctex", 8, 9))
        self.assertEqual(location_http.pick_answer(got)["warn"], STALE)

    def test_a_record_that_does_not_hold_the_file_or_cannot_be_read_counts_as_none(self):
        """A record of another file, a damaged record and a record that is a link to one: each is no record, so
        SyncTeX's numbers stand as they are."""
        self.edit("\\section{Intro}\n", ADDED)
        record = self.pages / built_source.SOURCE_NAME
        elsewhere = self.pages / "elsewhere.json"
        elsewhere.write_text(built_source.encode({"main.tex": TEX.splitlines()}), encoding="utf-8")
        for make in (
            lambda: record.write_text(built_source.encode({"other.tex": TEX.splitlines()}), encoding="utf-8"),
            lambda: record.write_text('{"format": 1, "files": {"main.tex": ', encoding="utf-8"),
            lambda: record.write_text('{"format": 1, "files": {"main.tex": [1, 2]}}', encoding="utf-8"),
            lambda: os.symlink(elsewhere, record),
        ):
            record.unlink(missing_ok=True)
            make()
            got = self.pick(8, 9)
            self.assertEqual((got.traced.raw_lo, got.traced.raw_hi), (8, 9))


class RealBuild(Base):
    """A real LaTeX build, picked against by name after the manuscript moved on."""

    def drag(self, build):
        """The pick request of a drag over the upper part of page 1 of build `build`."""
        page = limn_build.page_sizes(self.D.dir / build, ps.APP.C.dpi)[0]
        return {
            "page": 1,
            "x0": page["pt_w"] * 0.2,
            "y0": page["pt_h"] * 0.215,
            "x1": page["pt_w"] * 0.8,
            "y1": page["pt_h"] * 0.235,
            "pdf_build": build,
        }

    def raw_lines(self, answer):
        """The lines raw_lo..raw_hi of a pick answer, read from the manuscript as it is now."""
        now = self.main.read_text(encoding="utf-8").splitlines()
        return now[answer["raw_lo"] - 1 : answer["raw_hi"]]

    @needs_tex("latexmk", "pdftoppm", "pdftotext", "synctex")
    def test_a_pick_on_an_older_build_answers_the_text_that_was_dragged_after_edits_and_rebuilds(self):
        """Build, hold the build and ask where a drag lands; then add five lines above it, rebuild, add a comment
        line, rebuild again. The same drag on the first build answers the same text, five and then six lines lower,
        with no stale sentence. After the dragged lines are deleted it is refused or found elsewhere by its words -
        never answered at the numbers the first build knew."""
        self.D = ps.APP.docs[0]
        self.assertIsInstance(ps.APP.build_requests.build_all(self.D), BuildOk)
        first = limn_build.cur_pages(self.D).name
        self.assertTrue((self.D.dir / first / built_source.SOURCE_NAME).is_file())
        holds.set_hold(self.D, first, 1.0, "agent")  # keeps the first build's folder through the two rebuilds
        before = pick(self.drag(first))
        dragged = self.raw_lines(before)
        self.assertTrue(any("unique" in line for line in dragged), before)
        text = self.main.read_text(encoding="utf-8")
        self.main.write_text(text.replace("\\section{Intro}\n", ADDED, 1), encoding="utf-8")
        unbuilt = pick(self.drag(first))
        self.assertEqual(self.raw_lines(unbuilt), dragged, "edited and not rebuilt yet")
        self.assertEqual(unbuilt["raw_lo"], before["raw_lo"] + 5)
        self.assertEqual(unbuilt["warn"], "")
        self.assertIsInstance(ps.APP.build_requests.build_all(self.D, force=True), BuildOk)
        text = self.main.read_text(encoding="utf-8")
        self.main.write_text(text.replace("\\begin{document}\n", "\\begin{document}\n% a comment\n", 1), "utf-8")
        self.assertIsInstance(ps.APP.build_requests.build_all(self.D, force=True), BuildOk)
        self.assertTrue(limn_build.is_slimmed(self.D.dir / first))
        after = pick(self.drag(first))
        self.assertEqual(after["pdf_build"], first)
        self.assertEqual(self.raw_lines(after), dragged)
        self.assertEqual((after["raw_lo"], after["raw_hi"]), (before["raw_lo"] + 6, before["raw_hi"] + 6))
        self.assertEqual((after["lo"], after["hi"]), (before["lo"] + 6, before["hi"] + 6))
        self.assertEqual(after["warn"], "")
        text = self.main.read_text(encoding="utf-8")
        self.main.write_text(text.replace("\n".join(dragged) + "\n", "", 1), encoding="utf-8")
        gone = pick(self.drag(first))
        if "error" in gone:
            self.assertEqual(gone["reason"], "no_source_here")
        else:
            self.assertEqual(gone["via"], "text", gone)
            self.assertNotEqual((gone["raw_lo"], gone["raw_hi"]), (before["raw_lo"], before["raw_hi"]))

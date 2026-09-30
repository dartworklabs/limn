"""Figure pins as the listing reads them through the server: GET /api/pins and /api/pins/{id} carry the read-time
mark, mark_page and el_sync of each pin with an element, computed on the build on screen and never written - a
re-render moves or loses the mark without touching pins.jsonl or rev (docs/handbook/api.md §핀 읽기).

Run: uv run pytest -q src/limn/pins/listing/tests/test_figure_pins.py
"""

import json
from collections import Counter
from unittest import mock

from limn.builds import artifacts as build
from limn.runtime.documents import Doc
from limn.security.access import LOCAL_ACTOR

from helpers import Base, add_pin, edit_pin, find_record, jreq, ps, record_of, records, req, split_resp, write_records
from helpers_access import ALICE_ACTOR, BOB_ACTOR
from helpers_figure import (
    AUGUST,
    AUGUST_BOX,
    BUILD1,
    BUILD2,
    JULY,
    JULY_BOX,
    SCRIPT,
    b2_map,
    figure_doc,
    pin_from_pick,
    write_build,
)

FIELDS = ("mark", "mark_page", "el_sync")
HUGE = 10**400  # a JSON integer no float can hold


class FigureBase(Base):
    """A LaTeX document ms and figure document fig with BUILD1 on screen, and three pins on fig: the July cell (a line
    pin with el, Alice), the August cell (a region pin with el, Bob) and lines 20-22 without el (the agent)."""

    def setUp(self):
        """The documents, the build and the three pins."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())
        self.july = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "글자를 키워 줘")
        self.august = pin_from_pick(self.fig, AUGUST_BOX, BOB_ACTOR, "색을 바꿔 줘")
        self.plain = add_pin(
            {"doc": "fig", "file": SCRIPT, "lo": 20, "hi": 22, "note": "선 굵기"}, dict(LOCAL_ACTOR)
        ).core.pid

    def listed(self):
        """GET /api/pins?all=1 through the handler, by id."""
        code, _, body = split_resp(self.talk(req("GET", "/api/pins?all=1")))
        self.assertEqual(code, 200, body)
        return {p["id"]: p for p in json.loads(body)}

    def rewrite(self, pid, change):
        """Hand-edit the stored record of pin pid (the way an older or foreign writer left it): change(record) runs on the
        stored record, and pins.jsonl is written again. Nothing is validated beyond what the store keeps."""
        with ps.APP.RT.pin_lock:
            rows = records(ps.APP.read_pins()[0])
            change(next(r for r in rows if r["id"] == pid))
            write_records(rows)


class FigureReadTime(FigureBase):
    """The read-time position fields."""

    def test_each_element_pin_is_marked_where_its_element_is_on_the_build_on_screen(self):
        """Both element pins are ok at their element's box; the pin without el has none of the fields."""
        pins = self.listed()
        self.assertEqual(
            (pins[self.july]["mark"], pins[self.july]["mark_page"], pins[self.july]["el_sync"]), (list(JULY), 1, "ok")
        )
        self.assertEqual((pins[self.august]["mark"], pins[self.august]["el_sync"]), (list(AUGUST), "ok"))
        for key in ("mark", "mark_page", "el_sync"):
            self.assertNotIn(key, pins[self.plain])

    def test_a_re_render_moves_or_loses_the_mark_without_writing_the_pins(self):
        """The July cell moved and the August cell is gone on the new build: moved with the new box, lost without a
        mark - and pins.jsonl is the same bytes, rev still 0."""
        before = ps.APP.C.pins_jsonl.read_bytes()
        write_build(self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12), august=False))
        pins = self.listed()
        self.assertEqual((pins[self.july]["mark"], pins[self.july]["el_sync"]), ([0.4, 0.18, 0.07, 0.12], "moved"))
        self.assertEqual(pins[self.august]["el_sync"], "lost")
        self.assertNotIn("mark", pins[self.august])
        self.assertEqual([pins[i]["rev"] for i in (self.july, self.august)], [0, 0])
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)

    def test_an_editor_holding_the_pin_saves_after_its_element_is_lost(self):
        """An editor loaded rev before a re-render lost the element: its save with that base_rev is accepted."""
        rev = self.listed()[self.august]["rev"]
        write_build(self.fig, BUILD2, b2_map(august=False))
        self.assertEqual(self.listed()[self.august]["el_sync"], "lost")
        got = edit_pin(self.august, {"note": "색을 바꿔 줘(8월 칸)", "base_rev": rev}, dict(BOB_ACTOR))
        self.assertEqual(record_of(got)["note"], "색을 바꿔 줘(8월 칸)")

    def test_a_build_without_a_loadable_map_drops_the_fields(self):
        """The build on screen has no map copy: no element pin gets the fields."""
        write_build(self.fig, BUILD2, None)
        pins = self.listed()
        for pid in (self.july, self.august):
            self.assertNotIn("el_sync", pins[pid])

    def test_a_build_whose_map_the_parser_refuses_drops_the_fields(self):
        """The build on screen has a map copy that is not a map: the same as none - no element pin gets the fields."""
        d = write_build(self.fig, BUILD2, None)
        (d / build.FIGMAP_NAME).write_text('{"format": "not-a-limn-map"}', encoding="utf-8")
        pins = self.listed()
        for pid in (self.july, self.august):
            for key in FIELDS:
                self.assertNotIn(key, pins[pid])

    def test_one_pin_by_id_carries_the_fields_too(self):
        """GET /api/pins/{id} is the list's entry: el_sync is there."""
        code, _, body = split_resp(self.talk(req("GET", "/api/pins/%d" % self.july)))
        self.assertEqual((code, json.loads(body)["pin"]["el_sync"]), (200, "ok"))

    def test_the_fields_come_after_the_computed_ones_and_the_stored_record_is_unchanged(self):
        """The fields are last in the payload, and the stored record has none of them - a read never writes them."""
        code, _, body = split_resp(self.talk(req("GET", "/api/pins?all=1")))
        rec = next(p for p in json.loads(body) if p["id"] == self.july)
        self.assertEqual(list(rec)[-3:], list(FIELDS))
        stored = find_record(ps.APP.read_pins()[0], self.july)
        for key in FIELDS:
            self.assertNotIn(key, stored)

    def test_an_agents_pin_with_an_element_but_no_frac_is_found_and_never_ok(self):
        """An agent's line pin (el without frac, no frac of its own) on the July cell: the element is found where it is,
        and el_sync is moved, since nothing says where it was."""
        el = {"id": "B2/calendar/m07", "path": ["B2", "B2/calendar", "B2/calendar/m07"]}
        pid = add_pin(
            {"doc": "fig", "file": SCRIPT, "lo": 88, "hi": 95, "note": "n", "el": el}, dict(LOCAL_ACTOR)
        ).core.pid
        rec = self.listed()[pid]
        self.assertEqual((rec["mark"], rec["mark_page"], rec["el_sync"]), (list(JULY), 1, "moved"))


class FigureMapReads(FigureBase):
    """Each request reads a document's current map once, through the cache, however many pins point into it."""

    def more_pins(self, n):
        """n more element pins on the July cell, as Alice."""
        return [pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "다시 %d" % i) for i in range(n)]

    def test_one_request_with_many_figure_pins_asks_the_cache_once_and_parses_at_most_once(self):
        """Eight element pins of fig (seven on the July cell, one on the August cell) on a build whose map is not cached
        yet: GET /api/pins asks the run's cache for fig's current map once, the parse runs once, and the next request
        asks once more and parses nothing."""
        self.more_pins(6)
        write_build(self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12)))  # a copy the cache has not seen
        cache = ps.APP.RT.figure_maps
        with (
            mock.patch.object(cache, "get", wraps=cache.get) as asked,
            mock.patch.object(build, "parse_map", wraps=build.parse_map) as parsed,
        ):
            pins = self.listed()
            self.assertEqual([c.args[1] for c in asked.call_args_list], [BUILD2])
            self.assertEqual(parsed.call_count, 1)
            seen = Counter(p["el_sync"] for p in pins.values() if "el_sync" in p)
            self.assertEqual(seen, {"moved": 7, "ok": 1})  # the July cell moved, the August cell did not
            self.listed()
            self.assertEqual(asked.call_count, 2)
            self.assertEqual(parsed.call_count, 1)

    def test_a_pin_by_id_asks_for_its_documents_map_once(self):
        """GET /api/pins/{id} builds the whole list and picks one, so it too asks fig's map once, not once per pin."""
        self.more_pins(4)
        cache = ps.APP.RT.figure_maps
        with mock.patch.object(cache, "get", wraps=cache.get) as asked:
            code, _, _ = split_resp(self.talk(req("GET", "/api/pins/%d" % self.july)))
            self.assertEqual((code, asked.call_count), (200, 1))

    def test_a_list_without_element_pins_asks_no_map(self):
        """A LaTeX pin and a figure pin without el on their own: nothing asks the cache for a map."""
        rows = [r for r in records(ps.APP.read_pins()[0]) if "el" not in r]
        write_records(rows)
        cache = ps.APP.RT.figure_maps
        with mock.patch.object(cache, "get", wraps=cache.get) as asked:
            self.listed()
            self.assertEqual(asked.call_count, 0)

    def test_a_listing_of_pins_without_a_figure_document_asks_no_map(self):
        """An instance whose only document is LaTeX: a pin (even one carrying an el an older writer left) is listed and
        the cache is never asked - the document has no element map."""
        ps.APP.set_docs(None)
        cache = ps.APP.RT.figure_maps
        pid = self.add()
        self.rewrite(pid, lambda r: r.update(el={"id": "B2", "path": ["B2"]}))
        with mock.patch.object(cache, "get", wraps=cache.get) as asked:
            code, _, body = split_resp(self.talk(req("GET", "/api/pins")))
            rec = next(p for p in json.loads(body) if p["id"] == pid)
            self.assertEqual((code, "el_sync" in rec, asked.call_count), (200, False, 0))


class HostileStoredPins(FigureBase):
    """A pin whose stored el is as an older or foreign writer left it never fails the list."""

    def test_an_el_frac_the_store_keeps_but_no_reader_can_use_falls_back_and_never_raises(self):
        """A NaN, an oversized integer and a missing el.frac: the list answers 200, and the pin's el_sync comes from its
        own frac (the drag inside the July cell, not the cell's box), so moved, with the cell's box as the mark."""
        for name, change in (
            ("nan", lambda el: el.update(frac=[float("nan"), 0.18, 0.07, 0.12])),
            ("oversized", lambda el: el.update(frac=[HUGE, 0.18, 0.07, 0.12])),
            ("missing", lambda el: el.pop("frac")),
        ):
            with self.subTest(frac=name):
                self.rewrite(self.july, lambda r, edit=change: edit(r["el"]))
                rec = self.listed()[self.july]
                self.assertEqual((rec["el_sync"], rec["mark"], rec["mark_page"]), ("moved", list(JULY), 1))

    def test_an_el_frac_that_is_unusable_is_ok_when_the_pins_own_frac_is_the_elements_box(self):
        """The fallback compares the pin's own frac: when it is the box the element has, the pin is ok."""
        self.rewrite(self.july, lambda r: (r["el"].update(frac=[float("nan"), 0, 0, 0]), r.update(frac=list(JULY))))
        self.assertEqual(self.listed()[self.july]["el_sync"], "ok")

    def test_no_usable_frac_anywhere_is_moved_and_the_list_still_answers(self):
        """el.frac a NaN and the pin's own frac gone: the element is found and is never ok."""
        self.rewrite(self.july, lambda r: (r["el"].update(frac=[float("nan"), 0, 0, 0]), r.pop("frac", None)))
        rec = self.listed()[self.july]
        self.assertEqual((rec["el_sync"], rec["mark"]), ("moved", list(JULY)))

    def test_an_el_id_the_map_no_longer_has_is_lost_and_has_no_mark(self):
        """The element id is not on the build on screen: lost, with neither mark nor mark_page."""
        self.rewrite(self.july, lambda r: r["el"].update(id="B2/calendar/m99"))
        rec = self.listed()[self.july]
        self.assertEqual(rec["el_sync"], "lost")
        self.assertNotIn("mark", rec)
        self.assertNotIn("mark_page", rec)

    def test_a_hostile_pin_does_not_take_its_neighbours_fields_with_it(self):
        """One pin with a hostile el.frac beside two well-formed ones: the others are ok as before."""
        self.rewrite(self.july, lambda r: r["el"].update(frac=[HUGE, 0, 0, 0]))
        pins = self.listed()
        self.assertEqual((pins[self.july]["el_sync"], pins[self.august]["el_sync"]), ("moved", "ok"))

    def test_the_stored_hostile_record_is_not_rewritten_by_the_read(self):
        """Reading a list with hostile pins leaves pins.jsonl byte for byte as the hand edit wrote it."""
        self.rewrite(self.july, lambda r: r["el"].update(frac=[float("nan"), 0, 0, 0]))
        before = ps.APP.C.pins_jsonl.read_bytes()
        self.listed()
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)


class UnchangedPins(FigureBase):
    """Every pin that is not a figure pin with an element keeps exactly the keys it had."""

    # The keys and their order as GET /api/pins answered them before the read-time fields existed: the stored record's,
    # then rel, est, state, addressed and fyi (doc is stored, so it keeps its place).
    KEYS_LINE = [
        "file", "name", "lo", "hi", "page", "kind", "note", "at", "id", "author", "anchor", "synced_at", "pdf_build",
        "doc", "rev", "rel_path", "rel", "est", "state", "addressed", "fyi",
    ]  # fmt: skip
    KEYS_REGION = [
        "pdf", "name", "kind", "page", "frac", "note", "at", "id", "author", "pdf_build", "doc", "rev", "rel", "est",
        "state", "addressed", "fyi",
    ]  # fmt: skip

    def setUp(self):
        """A LaTeX line pin, a view-only PDF pin and a region pin without el on fig, beside the fixtures'."""
        super().setUp()
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        rv = Doc("rv", "리뷰", "pdf", self.src, self.src / "review.pdf", paths=ps.APP.C.paths)
        ps.APP.set_docs([*ps.APP.docs, rv])
        self.latex = self.add()
        self.pdf = add_pin(
            {"doc": "rv", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "쪽"}, dict(LOCAL_ACTOR)
        ).core.pid
        self.fig_region = add_pin(
            {"doc": "fig", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "그림 영역"}, dict(LOCAL_ACTOR)
        ).core.pid

    def test_no_pin_without_an_element_has_a_read_time_field(self):
        """A LaTeX line pin, a view-only PDF pin, a figure line pin and a figure region pin, the last two without el:
        none has mark, mark_page or el_sync."""
        pins = self.listed()
        for pid in (self.latex, self.pdf, self.plain, self.fig_region):
            for key in FIELDS:
                self.assertNotIn(key, pins[pid], pid)

    def test_a_latex_line_pin_keeps_its_exact_keys(self):
        """The keys and their order of a LaTeX line pin are the contract's: nothing is added."""
        self.assertEqual(list(self.listed()[self.latex]), self.KEYS_LINE)

    def test_region_and_view_only_pins_keep_their_exact_keys(self):
        """The keys of a view-only PDF pin and of a figure region pin without el are those of any region pin - neither
        gains a field."""
        pins = self.listed()
        for pid in (self.pdf, self.fig_region):
            self.assertEqual(list(pins[pid]), self.KEYS_REGION, pid)

    def test_a_figure_pin_without_an_element_keeps_its_exact_keys(self):
        """A line pin on a figure document that carries no el (an agent's curl): the keys of any line pin."""
        self.assertEqual(list(self.listed()[self.plain]), self.KEYS_LINE)

    def test_the_trash_list_and_a_change_requests_echo_carry_no_fields(self):
        """A dropped element pin in GET /api/pins/dropped, and the pin a claim answers with, have el but not mark,
        mark_page or el_sync: only the list and the single read follow the element."""
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/%d/claim" % self.july, {})))
        self.assertEqual(code, 200, body)
        echoed = json.loads(body)["pin"]
        self.assertIn("el", echoed)
        for key in FIELDS:
            self.assertNotIn(key, echoed)
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/%d/drop" % self.august, {})))
        self.assertEqual(code, 200, body)
        code, _, body = split_resp(self.talk(req("GET", "/api/pins/dropped")))
        dropped = [p for p in json.loads(body)["dropped"] if p["id"] == self.august]
        self.assertEqual((code, len(dropped)), (200, 1))
        self.assertIn("el", dropped[0])
        for key in FIELDS:
            self.assertNotIn(key, dropped[0])

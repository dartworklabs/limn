"""Figure pins as the listing reads them through the server: GET /api/pins and /api/pins/{id} carry the read-time
mark, mark_page and el_sync of each pin with an element, computed on the build on screen and never written - a
re-render moves or loses the mark without touching pins.jsonl or rev (docs/handbook/api.md §그림 문서의 pick·핀) - and pins.md
shows the same pins as rows: the element's «label», its shared part and 요소 잃음, rendered on request through the
same per-request map lookup (docs/handbook/api.md §그림 핀의 행).

Run: uv run pytest -q src/limn/pins/listing/tests/test_figure_pins.py
"""

import contextlib
import io
import json
import os
from collections import Counter
from unittest import mock

from limn.builds import artifacts as build
from limn.builds.artifacts import BuildFailed, BuildOk
from limn.pins.listing import render
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
    import_build,
    pin_from_pick,
    write_build,
)

FIELDS = ("mark", "mark_page", "el_sync")
HUGE = 10**400  # a JSON integer no float can hold
LATEX_OK = BuildOk("", 0.1, None, None, "h" * 32, "-", "pages-20260926120000", 1)  # what a LaTeX build hands back


def pins_md_stamp() -> tuple[int, int]:
    """The identity of pins.md on disk: inode and mtime in ns - a rewrite (atomic replace) changes both."""
    st = ps.APP.C.pins_md.stat()
    return st.st_ino, st.st_mtime_ns


def age_pins_md() -> tuple[int, int]:
    """Give pins.md on disk an old mtime, so a later rewrite cannot leave it looking the same; its new stamp."""
    old = 1_000_000_000 * 10**9
    os.utime(ps.APP.C.pins_md, ns=(old, old))
    return pins_md_stamp()


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

    def row(self, md, pid):
        """The table row of pin pid."""
        return next(
            line for line in md.splitlines() if line.startswith("| %d |" % pid) or line.startswith("| %d · " % pid)
        )

    def rewrite(self, pid, change):
        """Hand-edit the stored record of pin pid (the way an older or foreign writer left it): change(record) runs on
        the stored record, and pins.jsonl is written again. Nothing is validated beyond what the store keeps."""
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

    def test_a_latex_document_never_reads_its_pages_for_a_figure_map(self):
        """doc_figure_map of a LaTeX document is None and asks neither the cache nor which build is on screen: the
        capability is checked before pages.cur is read. A figure document still answers its map."""
        cache = ps.APP.RT.figure_maps
        with (
            mock.patch.object(cache, "get", wraps=cache.get) as asked,
            mock.patch.object(build, "cur_pages", wraps=build.cur_pages) as shown,
        ):
            self.assertIsNone(ps.APP.doc_figure_map("ms"))
            self.assertIsNone(ps.APP.doc_figure_map("gone"))
            self.assertEqual((asked.call_count, shown.call_count), (0, 0))
            self.assertIsNotNone(ps.APP.doc_figure_map("fig"))
            self.assertEqual((asked.call_count, shown.call_count), (1, 1))

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


class NonFiniteNumbers(FigureBase):
    """A hand-edited or legacy pins.jsonl that holds NaN or Infinity in a stored number: every endpoint that echoes a
    stored record answers strict JSON (what the browser's JSON.parse reads). A frac or el.frac with any such entry reads
    null as a whole, any other such number reads null, and the stored bytes stay as they were."""

    def setUp(self):
        """July (a line pin with el) gets a NaN in frac and an Infinity in el.frac; August (a region pin with el) a
        negative Infinity in frac and a NaN in el.frac - written the way json.dumps writes them."""
        super().setUp()
        nan, inf = float("nan"), float("inf")
        self.rewrite(
            self.july, lambda r: (r.update(frac=[nan, 0.1, 0.2, 0.3]), r["el"].update(frac=[inf, 0.1, 0.2, 0.3]))
        )
        self.rewrite(
            self.august, lambda r: (r.update(frac=[-inf, 0.1, 0.2, 0.3]), r["el"].update(frac=[0.1, nan, 0.2, 0.3]))
        )
        self.stored = ps.APP.C.pins_jsonl.read_bytes()

    @staticmethod
    def strict(body):
        """json.loads with NaN and Infinity refused, as JSON.parse refuses them."""

        def refuse(name):
            """A non-finite constant on the wire is a failure."""
            raise AssertionError("non-finite constant on the wire: " + name)

        return json.loads(body, parse_constant=refuse)

    def get(self, path):
        """GET path through the handler: the status is 200 and the body parses strictly."""
        code, _, body = split_resp(self.talk(req("GET", path)))
        self.assertEqual(code, 200, body)
        return self.strict(body)

    def test_the_stored_lines_really_hold_the_non_finite_numbers(self):
        """Guard for the fixture: the hand edit wrote NaN and Infinity tokens, so the tests below are not vacuous."""
        self.assertIn(b"NaN", self.stored)
        self.assertIn(b"Infinity", self.stored)

    def test_the_list_answers_strict_json_with_null_and_leaves_the_file_alone(self):
        """GET /api/pins?all=1: frac and el.frac of both pins read null as a whole, and the read-time fields are
        still there; pins.jsonl is the same bytes."""
        pins = {p["id"]: p for p in self.get("/api/pins?all=1")}
        self.assertEqual(pins[self.july]["frac"], None)
        self.assertEqual(pins[self.july]["el"]["frac"], None)
        self.assertEqual(pins[self.august]["frac"], None)
        self.assertEqual(pins[self.august]["el"]["frac"], None)
        self.assertIn("el_sync", pins[self.july])
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), self.stored)

    def test_one_pin_by_id_answers_strict_json_with_null(self):
        """GET /api/pins/{id}: the same nulls in the single pin's frac and el.frac; the file is unchanged."""
        pin = self.get("/api/pins/%d" % self.july)["pin"]
        self.assertEqual((pin["frac"], pin["el"]["frac"]), (None, None))
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), self.stored)

    def test_the_trash_list_answers_strict_json_with_null(self):
        """A dropped pin that holds the numbers is listed from the Trash file with null in their place, and the Trash
        file keeps the stored numbers."""
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/%d/drop" % self.august, {})))
        self.assertEqual(code, 200, body)
        self.strict(body)
        trash = ps.APP.C.state / "pins.dropped.jsonl"
        kept = trash.read_bytes()
        dropped = {p["id"]: p for p in self.get("/api/pins/dropped")["dropped"]}
        self.assertEqual(dropped[self.august]["frac"], None)
        self.assertEqual(dropped[self.august]["el"]["frac"], None)
        self.assertIn(b"NaN", kept)
        self.assertEqual(trash.read_bytes(), kept)

    def test_a_change_requests_echo_answers_strict_json_with_null(self):
        """POST claim answers with the pin it changed: its frac reads null where it was non-finite."""
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/%d/claim" % self.july, {})))
        self.assertEqual(code, 200, body)
        echoed = self.strict(body)["pin"]
        self.assertEqual((echoed["frac"], echoed["el"]["frac"]), (None, None))

    def test_every_other_stored_number_reads_null_in_the_list_and_the_file_is_unchanged(self):
        """score, claim_ts, claim_until and eta_ts of a pin hold NaN and Infinity (a claim that never lapses): the list
        answers strict JSON with null for each, and pins.jsonl keeps the stored numbers."""
        nan, inf = float("nan"), float("inf")
        bob = {"login": "bob@example.com", "name": "Bob"}
        self.rewrite(
            self.august,
            lambda r: r.update(score=nan, claim_ts=nan, claim_until=inf, eta_ts=-inf, claimed_by=bob, claimed_at="t"),
        )
        stored = ps.APP.C.pins_jsonl.read_bytes()
        pin = {p["id"]: p for p in self.get("/api/pins?all=1")}[self.august]
        for key in ("score", "claim_ts", "claim_until", "eta_ts"):
            self.assertIn(key, pin)
            self.assertIsNone(pin[key], key)
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), stored)

    def test_a_refused_claim_answers_strict_json_when_the_holders_numbers_are_not_finite(self):
        """Another identity holds a claim that never lapses (claim_until Infinity, eta_ts NaN): the 409 names the
        holder and answers both numbers as null, so the body is strict JSON."""
        bob = {"login": "bob@example.com", "name": "Bob"}
        self.rewrite(
            self.august,
            lambda r: r.update(claim_until=float("inf"), eta_ts=float("nan"), claimed_by=bob, claimed_at="t"),
        )
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/%d/claim" % self.august, {})))
        self.assertEqual(code, 409, body)
        refused = self.strict(body)
        self.assertEqual((refused["reason"], refused["claimed_by"]), ("claimed", bob))
        self.assertEqual((refused["claim_until"], refused["eta_ts"]), (None, None))

    def test_finite_bounds_are_echoed_unchanged(self):
        """frac and el.frac made of 0.0 and 1.0 (the page's corners) come back exactly as stored."""
        self.rewrite(
            self.july, lambda r: (r.update(frac=[0.0, 0.0, 1.0, 1.0]), r["el"].update(frac=[1.0, 0.0, 0.0, 1.0]))
        )
        pin = self.listed()[self.july]
        self.assertEqual((pin["frac"], pin["el"]["frac"]), ([0.0, 0.0, 1.0, 1.0], [1.0, 0.0, 0.0, 1.0]))


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


class FigureMarkdown(FigureBase):
    """pins.md for the three figure pins, rendered as the store writes it."""

    def md(self, only=None):
        """pins.md over the live pins (only those whose id is in only, when given) - a render, no write."""
        pins = ps.APP.snapshot_pins()
        return ps.APP.pin_markdown.pins_md_text([p for p in pins if only is None or p.core.pid in only])

    def test_the_figure_section_is_titled_as_a_figure(self):
        """The figure document's subsection title ends with — 그림(요소 지도), never the view-only suffix."""
        lines = self.md().splitlines()
        self.assertIn("## 그림 · `fig` · `figs/out/figures.limnmap.json` — 그림(요소 지도)", lines)
        self.assertFalse(any("보기 전용 PDF(줄 번호 없음)" in line for line in lines))

    def test_the_document_list_does_not_call_the_figure_view_only(self):
        """The figure takes line pins, so the list names it as any document with them: its key and its pin count."""
        self.assertIn("문서: 본문(`ms`) 0건 · 그림(`fig`) 3건", self.md())
        self.assertNotIn("보기 전용", self.md())

    def test_rows_name_the_element_and_its_shared_part_manuscript_relative(self):
        """The July row: the script lines, the kind, «7월» and the shared part under figs/; the clause is there."""
        md = self.md()
        row = self.row(md, self.july)
        self.assertIn("| `%s L88-L95` | el:MonthCell | «7월» " % SCRIPT, row)
        self.assertTrue(row.endswith("⏎ 공통 부품: figs/lib/components.py:410-470 |"), row)
        self.assertIn(render.FIGURE_GUIDANCE, md)

    def test_an_agent_pin_without_el_is_a_plain_row_and_brings_no_clause(self):
        """The pin without el has no «…»; rendered alone, pins.md has no figure clause."""
        self.assertNotIn("«", self.row(self.md(), self.plain))
        self.assertNotIn(render.FIGURE_GUIDANCE, self.md(only={self.plain}))

    def test_a_lost_element_is_marked_in_the_number_cell(self):
        """After a re-render without the August cell its row says 요소 잃음."""
        write_build(self.fig, BUILD2, b2_map(august=False))
        self.assertIn("요소 잃음", self.row(self.md(), self.august))

    def test_a_moved_element_is_not_marked_lost(self):
        """The July cell moved and is still on the map: no 요소 잃음 in its row."""
        write_build(self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12)))
        self.assertNotIn("요소 잃음", self.row(self.md(), self.july))

    def test_a_build_without_a_loadable_map_marks_nothing_lost(self):
        """No map to follow the element on: not a loss - the row has no 요소 잃음, and the render still answers."""
        write_build(self.fig, BUILD2, None)
        md = self.md()
        for pid in (self.july, self.august):
            self.assertNotIn("요소 잃음", self.row(md, pid))

    def test_get_pins_md_renders_the_build_on_screen_on_request(self):
        """A build put on screen without an import (no hook ran) still shows in GET /pins.md, which renders on request:
        the August row already says 요소 잃음. The guidance explains the word, so it is the pin's row that is compared, not
        the whole text. The limit of the file on disk is docs/handbook/domain.md §그림 핀의 한계."""
        write_build(self.fig, BUILD2, b2_map(august=False))
        code, _, body = split_resp(self.talk(req("GET", "/pins.md")))
        self.assertEqual(code, 200)
        self.assertIn("요소 잃음", self.row(body.decode("utf-8"), self.august))

    def test_an_import_rewrites_the_file_on_disk_so_a_local_agent_reads_the_lost_element(self):
        """The tracked import of a re-render without the August cell rewrites pins.md on disk - the file an agent on
        this machine reads - so its row says 요소 잃음 with no GET and no pin write in between; the July cell only moved, so
        its row does not; pins.jsonl is the same bytes and every rev is still 0."""
        before = ps.APP.C.pins_jsonl.read_bytes()
        self.assertNotIn("요소 잃음", self.row(ps.APP.C.pins_md.read_text(encoding="utf-8"), self.august))
        done = import_build(ps.APP, self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12), august=False))
        self.assertIsInstance(done, BuildOk)
        self.assertEqual(build.cur_pages(self.fig).name, BUILD2)
        on_disk = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("요소 잃음", self.row(on_disk, self.august))
        self.assertNotIn("요소 잃음", self.row(on_disk, self.july))
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)
        self.assertEqual([r.get("rev", 0) for r in records(ps.APP.read_pins()[0])], [0, 0, 0])

    def test_a_latex_build_leaves_pins_md_alone(self):
        """A LaTeX document's build that succeeds writes no pins.md: the file keeps its inode and its (aged) mtime."""
        aged = age_pins_md()
        ms = ps.APP.docs[0]
        with mock.patch.object(ps.APP.build_requests, "compile", return_value=LATEX_OK):
            self.assertIsInstance(ps.APP.build_requests.build_all(ms), BuildOk)
        self.assertEqual(pins_md_stamp(), aged)

    def test_an_import_that_does_not_land_leaves_pins_md_alone(self):
        """A render that fails commits no page directory, so nothing is on screen that pins.md could follow: the file is
        not rewritten and pages.cur still names the build before."""
        aged = age_pins_md()
        done = import_build(ps.APP, self.fig, BUILD2, b2_map(august=False), renders=False)
        self.assertIsInstance(done, BuildFailed)
        self.assertEqual(build.cur_pages(self.fig).name, BUILD1)
        self.assertEqual(pins_md_stamp(), aged)

    def test_an_import_rewrites_the_file_once(self):
        """One import is one rewrite of pins.md - the control of the two tests above: the aged file is replaced."""
        aged = age_pins_md()
        import_build(ps.APP, self.fig, BUILD2, b2_map(august=False))
        self.assertNotEqual(pins_md_stamp(), aged)

    def test_a_refresh_that_fails_keeps_the_old_file_and_the_import_still_lands(self):
        """The render of pins.md raises: the file stays as it was (rendering happens before the write), the error goes
        to stderr, and the import is still a good build - pages.cur moved, the build state says ok."""
        aged = age_pins_md()
        err = io.StringIO()
        with (
            mock.patch.object(ps.APP.pin_markdown, "pins_md_text", side_effect=RuntimeError("render broke")),
            contextlib.redirect_stderr(err),
        ):
            done = import_build(ps.APP, self.fig, BUILD2, b2_map(august=False))
        self.assertIsInstance(done, BuildOk)
        self.assertEqual(build.cur_pages(self.fig).name, BUILD2)
        self.assertEqual(build.state_snapshot(self.fig)["state"], "ok")
        self.assertEqual(pins_md_stamp(), aged)
        self.assertIn("render broke", err.getvalue())

    def test_the_file_the_store_wrote_shows_the_same_rows(self):
        """pins.md on disk (written after the last pin write in setUp) has the figure title, the part and the clause."""
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn(" — 그림(요소 지도)", text)
        self.assertIn("공통 부품: figs/lib/components.py:410-470", text)
        self.assertIn(render.FIGURE_GUIDANCE, text)

    def test_a_region_pin_on_the_figure_is_guided_to_the_figure_not_to_latex(self):
        """The August cell (drawn without code) is a region pin with an element: «8월» before its note, the figure
        clause, and no 'LaTeX 문서에서 찾는다' anywhere - the view-only clause is only for PDF documents."""
        md = self.md()
        self.assertIn("«8월» ", self.row(md, self.august))
        self.assertIn("색을 바꿔 줘", self.row(md, self.august))
        self.assertNotIn("보기 전용 PDF 의 핀은 줄 번호가 없다", md)
        self.assertNotIn("LaTeX 문서에서 찾는다", md)

    def test_a_region_pin_without_an_element_on_the_figure_is_guided_to_the_figure_too(self):
        """A pick that fell back because the map could not be read leaves a region pin without el: with only that pin
        open, the sheet still points at the figure repository, not at LaTeX."""
        pid = add_pin(
            {"doc": "fig", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "영역"}, dict(LOCAL_ACTOR)
        ).core.pid
        md = self.md(only={pid})
        self.assertIn(render.FIGURE_GUIDANCE, md)
        self.assertNotIn("LaTeX 문서에서 찾는다", md)

    def test_a_view_only_pdf_document_keeps_its_own_clause(self):
        """A region pin on a view-only PDF document beside the figure: its title, its clause, and the figure's own."""
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        rv = Doc("rv", "리뷰", "pdf", self.src, self.src / "review.pdf", paths=ps.APP.C.paths)
        ps.APP.set_docs([*ps.APP.docs, rv])
        add_pin({"doc": "rv", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "쪽"}, dict(LOCAL_ACTOR))
        md = self.md()
        self.assertIn("## 리뷰 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)", md.splitlines())
        self.assertIn("리뷰(`rv`, 보기 전용) 1건", md)
        self.assertIn("고칠 곳은 LaTeX 문서에서 찾는다", md)
        self.assertIn(render.FIGURE_GUIDANCE, md)


class FigureMarkdownMapReads(FigureBase):
    """A render looks up each document's current map once, through the run's cache, however many pins point into it."""

    def render(self, base=None):
        """pins.md over the live pins, as the store writes it (base None) or GET /pins.md renders it."""
        return ps.APP.pin_markdown.pins_md_text(ps.APP.snapshot_pins(), base)

    def test_a_render_asks_the_cache_once_and_parses_at_most_once(self):
        """Eight element pins of fig on a build whose map is not cached yet: one render asks the cache for fig's map
        once and parses it once; the next render asks once more and parses nothing."""
        for i in range(6):
            pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "다시 %d" % i)
        write_build(self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12)))  # a copy the cache has not seen
        cache = ps.APP.RT.figure_maps
        with (
            mock.patch.object(cache, "get", wraps=cache.get) as asked,
            mock.patch.object(build, "parse_map", wraps=build.parse_map) as parsed,
        ):
            self.render()
            self.assertEqual([c.args[1] for c in asked.call_args_list], [BUILD2])
            self.assertEqual(parsed.call_count, 1)
            self.render()
            self.assertEqual(asked.call_count, 2)
            self.assertEqual(parsed.call_count, 1)

    def test_get_pins_md_asks_the_cache_once_too(self):
        """GET /pins.md with many element pins: one lookup of fig's map, not one per pin."""
        for i in range(4):
            pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "다시 %d" % i)
        cache = ps.APP.RT.figure_maps
        with mock.patch.object(cache, "get", wraps=cache.get) as asked:
            code, _, _ = split_resp(self.talk(req("GET", "/pins.md")))
            self.assertEqual((code, asked.call_count), (200, 1))

    def test_a_render_without_element_pins_asks_no_map(self):
        """Only pins without el (a LaTeX pin, a figure line pin): the cache is never asked."""
        write_records([r for r in records(ps.APP.read_pins()[0]) if "el" not in r])
        cache = ps.APP.RT.figure_maps
        with mock.patch.object(cache, "get", wraps=cache.get) as asked:
            self.render()
            self.assertEqual(asked.call_count, 0)

    def test_a_pin_write_renders_pins_md_with_one_lookup(self):
        """The render the store does after a pin write (the file on disk) is one lookup as well."""
        cache = ps.APP.RT.figure_maps
        with mock.patch.object(cache, "get", wraps=cache.get) as asked:
            add_pin({"doc": "fig", "file": SCRIPT, "lo": 30, "hi": 31, "note": "또"}, dict(LOCAL_ACTOR))
            self.assertEqual(asked.call_count, 1)

    def test_a_render_never_writes_a_pin(self):
        """pins.jsonl is the same bytes and every rev is still 0 after a render of a re-rendered figure, lost element
        included."""
        write_build(self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12), august=False))
        before = ps.APP.C.pins_jsonl.read_bytes()
        md = self.render()
        code, _, _ = split_resp(self.talk(req("GET", "/pins.md")))
        self.assertEqual(code, 200)
        self.assertIn("요소 잃음", self.row(md, self.august))
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)
        self.assertEqual([r.get("rev", 0) for r in records(ps.APP.read_pins()[0])], [0, 0, 0])


class FigureMarkdownSharedPart(FigureBase):
    """The shared part is text joined under the document's folder: nothing is opened, and only a plain path is
    printed."""

    def md(self):
        """GET /pins.md's text."""
        code, _, body = split_resp(self.talk(req("GET", "/pins.md")))
        self.assertEqual(code, 200, body)
        return body.decode("utf-8")

    def set_impl_file(self, file):
        """Hand-edit the July pin's stored el.impl.file (a line an older writer or a person left)."""
        self.rewrite(self.july, lambda r: r["el"]["impl"].update(file=file))

    def test_a_hostile_stored_file_is_left_out_and_the_rest_of_the_row_stays(self):
        """'..', an absolute path, a dot folder, a backslash and an empty part in a stored impl.file: no 공통 부품, no '..'
        and no absolute path in pins.md, and the row still has its lines, kind and «7월»."""
        for bad in (
            "../../secret.py",
            "lib/../../secret.py",
            "/etc/passwd",
            ".git/config",
            "lib/.env",
            "lib\\a.py",
            "lib//a.py",
            "./a.py",
            "",
        ):
            with self.subTest(file=bad):
                self.set_impl_file(bad)
                md = self.md()
                row = self.row(md, self.july)
                self.assertNotIn("공통 부품", row)
                self.assertIn("| `%s L88-L95` | el:MonthCell | «7월» " % SCRIPT, row)
                self.assertNotIn("secret.py", md)
                self.assertNotIn("/etc/passwd", md)
                self.assertNotIn("..", row.replace("...", ""))

    def test_the_part_is_printed_without_opening_the_file_it_names(self):
        """The shared file is gone: the line is still printed, and no stat, open or readlink is made on a path ending in
        the impl file."""
        components = self.fig.src / "lib" / "components.py"
        components.unlink()
        seen = []
        real = {name: getattr(os, name) for name in ("stat", "lstat", "readlink", "open", "scandir")}

        def spy(name):
            """The os function name, recording any path that names the shared file."""

            def call(path, *a, **kw):
                """Record path when it ends in lib/components.py, then do the real call."""
                if isinstance(path, (str, bytes, os.PathLike)) and os.fsdecode(path).endswith("lib/components.py"):
                    seen.append((name, os.fsdecode(path)))
                return real[name](path, *a, **kw)

            return call

        with contextlib.ExitStack() as stack:
            for name in real:
                stack.enter_context(mock.patch.object(os, name, spy(name)))
            md = self.md()
        self.assertIn("공통 부품: figs/lib/components.py:410-470", self.row(md, self.july))
        self.assertEqual(seen, [])

    def test_a_shared_part_that_is_a_link_out_of_the_tree_is_printed_as_text_only(self):
        """lib/components.py made a symlink to a file outside the manuscript: pins.md names it by its text and never
        follows it."""
        components = self.fig.src / "lib" / "components.py"
        components.unlink()
        outside = self.src.parent / "outside.py"
        outside.write_text("x = 1\n", encoding="utf-8")
        components.symlink_to(outside)
        md = self.md()
        self.assertIn("공통 부품: figs/lib/components.py:410-470", self.row(md, self.july))
        self.assertNotIn("outside.py", md)

    def test_a_pin_whose_document_is_no_longer_served_prints_no_part(self):
        """The pin names a document the instance no longer has: the shared file's folder is unknown, so no part - the
        row is under the unknown-document section with its «label»."""
        self.rewrite(self.july, lambda r: r.update(doc="gone"))
        md = self.md()
        row = self.row(md, self.july)
        self.assertNotIn("공통 부품", row)
        self.assertIn("«7월»", row)
        self.assertIn("## 설정에 없는 문서 · `gone`", md)

    def test_a_pin_whose_document_is_now_a_latex_document_prints_no_part(self):
        """The key `fig` is reconfigured as a LaTeX document: its pins are served again, but a LaTeX document has no
        element map, so the shared part's folder is unknown and the row prints no 공통 부품."""
        latex = Doc("fig", "그림", "tex", self.src, self.main, paths=ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), latex])
        row = self.row(self.md(), self.july)
        self.assertNotIn("공통 부품", row)

    def test_hostile_stored_records_render_and_change_nothing(self):
        """A NaN or oversized el.frac and reversed impl lines: pins.md answers 200, prints no part for the bad lines,
        and pins.jsonl is byte for byte as the hand edit wrote it."""
        self.rewrite(
            self.july, lambda r: (r["el"].update(frac=[float("nan"), 0, 0, 0]), r["el"]["impl"].update(lo=9, hi=3))
        )
        self.rewrite(self.august, lambda r: r["el"].update(frac=[HUGE, 0.18, 0.07, 0.12]))
        before = ps.APP.C.pins_jsonl.read_bytes()
        md = self.md()
        self.assertNotIn("공통 부품", self.row(md, self.july))
        self.assertIn("«8월»", self.row(md, self.august))
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)

"""Figure pins through pin creation and editing: POST /api/pin and /api/pins/{id}/edit keep a figure pin's el
(pins/editing), a figure document takes line pins (Doc.takes_line_pins), an agent's curl without el is a plain
line pin routed by its file, and a malformed el is 400 bad_el with nothing stored. parse_el is checked on its own
first. docs/handbook/api.md §그림 문서의 pick·핀 is the contract they extend.

Run: uv run pytest -q src/limn/pins/editing/tests/test_figure_pins.py
"""

import json
import unittest

from limn.pins.editing.input import REGION_EDIT_REFUSAL
from limn.pins.editing.location import (
    EL_FILE_MAX,
    EL_LINE_MAX,
    EL_PATH_MAX,
    EL_REFUSAL,
    EL_TEXT_MAX,
    parse_el,
    parse_region,
)
from limn.pins.element import EL_TEXT_MAX as MAP_MAX_TEXT, ElementImpl, PinElement
from limn.runtime.documents import Doc
from limn.security.access import LOCAL_ACTOR
from limn.web.errors import InputRejected

from helpers import Base, add_pin, edit_pin, edit_stored, fits, jreq, ps, record_of, req, split_resp
from helpers_access import ALICE_ACTOR, BOB_ACTOR
from helpers_figure import AUGUST_BOX, BUILD1, JULY_BOX, SCRIPT, b2_map, figure_doc, pin_from_pick, write_build

GOOD = {"id": "B2/calendar/m07", "path": ["B2", "B2/calendar", "B2/calendar/m07"]}
# An el as a hand-written or older store may hold it: keys out of the canonical order, an integer frac, a key the
# contract does not have and a null label - everything PinElement.to_record would change.
ODD_EL = {
    "path": ["B2", "B2/calendar", "B2/calendar/m07"],
    "frac": [0, 0, 1, 1],
    "future": {"b": ["7월", 2], "a": None},
    "id": "B2/calendar/m07",
    "label": None,
    "part": "MonthCell",
}


def el_text(el: object) -> str:
    """An el as the store writes it (one JSON value, non-ASCII kept), so two of them compare byte for byte."""
    return json.dumps(el, ensure_ascii=False)


class ParseEl(unittest.TestCase):
    """parse_el: the el a request sends, parsed once at the boundary."""

    def test_a_well_formed_el_is_its_value_and_unknown_keys_are_dropped(self):
        """Every field comes over; a key the contract does not have is dropped, as unknown top-level fields are."""
        got = parse_el(
            {
                **GOOD,
                "label": "7월",
                "part": "MonthCell",
                "impl": {"file": "lib/components.py", "lo": 410, "hi": 470, "x": 1},
                "frac": [0.47, 0.18, 0.07, 0.12],
                "future": True,
            }
        )
        self.assertEqual(
            got,
            PinElement(
                "B2/calendar/m07",
                ("B2", "B2/calendar", "B2/calendar/m07"),
                "7월",
                "MonthCell",
                ElementImpl("lib/components.py", 410, 470),
                (0.47, 0.18, 0.07, 0.12),
            ),
        )
        self.assertIsNone(parse_el(None))

    def test_the_refusal_sentence_is_the_contracts_and_its_limit_is_the_maps_text_limit(self):
        """The bad_el sentence is byte-identical to the one agents already read, and the number of characters in it is
        MAP_MAX_TEXT, the bound parse_el enforces."""
        self.assertEqual(
            EL_REFUSAL,
            "el 은 pick 이 준 요소 {id, path, label?, part?, impl?: {file, lo, hi}, frac?} 여야 합니다"
            "(문자열 200자 이하, path 는 뿌리부터 그 요소까지의 id, impl.file 은 문서 폴더 기준 상대 경로).",
        )
        self.assertIn("문자열 %d자 이하" % MAP_MAX_TEXT, EL_REFUSAL)
        self.assertEqual(
            parse_el({"id": "x" * (MAP_MAX_TEXT + 1), "path": ["x" * (MAP_MAX_TEXT + 1)]}).message, EL_REFUSAL
        )

    def test_a_malformed_el_is_bad_el(self):
        """Not an object; a bad id or path (empty, not strings, not ending with the id, too long); a non-string label
        or part; an impl that is absolute, climbs out, is backwards or not integers; a frac off the page."""
        for bad in (
            "B2",
            {"path": ["B2"]},
            {**GOOD, "id": ""},
            {**GOOD, "path": "B2"},
            {**GOOD, "path": []},
            {**GOOD, "path": ["B2"]},
            {**GOOD, "path": ["B2", 7, "B2/calendar/m07"]},
            {**GOOD, "label": 7},
            {**GOOD, "part": ["x"]},
            {**GOOD, "label": "x" * (EL_TEXT_MAX + 1)},
            {**GOOD, "impl": "lib.py:1-2"},
            {**GOOD, "impl": {"file": "/etc/passwd", "lo": 1, "hi": 2}},
            {**GOOD, "impl": {"file": "../lib.py", "lo": 1, "hi": 2}},
            {**GOOD, "impl": {"file": "lib.py", "lo": 3, "hi": 2}},
            {**GOOD, "impl": {"file": "lib.py", "lo": True, "hi": 2}},
            {**GOOD, "frac": [0.9, 0.1, 0.5, 0.1]},
            {**GOOD, "frac": [0.1, 0.1, 0.0, 0.1]},
        ):
            with self.subTest(bad=bad):
                self.assertEqual(parse_el(bad).reason, "bad_el")

    def test_an_empty_label_or_part_is_not_sent(self):
        """The pick leaves an empty label or part out, so a request that sends one gets the same element: absent."""
        got = parse_el({**GOOD, "label": "", "part": ""})
        self.assertEqual((got.label, got.part), (None, None))
        self.assertEqual(got.to_record(), GOOD)

    def test_the_limits_are_the_maps(self):
        """A map's text, depth, path and line limits are the ones a pin's el is held to, so every element a map may hold
        can be pinned."""
        self.assertEqual((EL_TEXT_MAX, EL_PATH_MAX, EL_FILE_MAX, EL_LINE_MAX), (200, 64, 1024, 1_000_000))

    def test_an_impl_file_must_be_a_canonical_relative_path(self):
        """The rule a map's src.file and impl.file are held to (limn.builds.figure_map.is_canonical_path): a '..', '.'
        or empty part, a leading or trailing '/', a backslash, a NUL, nothing at all, and more than EL_FILE_MAX
        characters are bad_el."""
        for file in (
            "",
            "..",
            "../lib.py",
            "a/../lib.py",
            "a/..",
            ".",
            "./lib.py",
            "a/./lib.py",
            "a//lib.py",
            "/lib.py",
            "lib/",
            "a\\lib.py",
            "a\x00lib.py",
            "x" * (EL_FILE_MAX + 1),
        ):
            with self.subTest(file=file):
                got = parse_el({**GOOD, "impl": {"file": file, "lo": 1, "hi": 2}})
                self.assertIsInstance(got, InputRejected)
                self.assertEqual(got.reason, "bad_el")

    def test_a_canonical_impl_file_at_the_length_limit_is_kept(self):
        """The longest allowed file, a dotted name and a nested path all pass: only the forbidden parts are refused."""
        for file in ("x" * EL_FILE_MAX, "lib/.hidden.py", "a..b/c.py", "lib/components.py"):
            with self.subTest(file=file):
                got = parse_el({**GOOD, "impl": {"file": file, "lo": 1, "hi": 2}})
                self.assertEqual(got.impl, ElementImpl(file, 1, 2))

    def test_the_text_path_and_line_limits_are_inclusive(self):
        """At the limit an el is kept (a 200-character id and label, 64 ids in the path, impl lines up to 1,000,000);
        one past it is bad_el."""
        eid = "e" * EL_TEXT_MAX
        path = ["p%d" % i for i in range(EL_PATH_MAX - 1)] + [eid]
        top = {
            "id": eid,
            "path": path,
            "label": "l" * EL_TEXT_MAX,
            "impl": {"file": "a.py", "lo": 1, "hi": EL_LINE_MAX},
        }
        got = parse_el(top)
        self.assertIsInstance(got, PinElement)
        self.assertEqual((len(got.id), len(got.path), len(got.label), got.impl.hi), (200, 64, 200, 1_000_000))
        over_id = "e" * (EL_TEXT_MAX + 1)
        for name, bad in (
            ("id", {**top, "id": over_id, "path": path[:-1] + [over_id]}),
            ("label", {**top, "label": "l" * (EL_TEXT_MAX + 1)}),
            ("part", {**top, "part": "p" * (EL_TEXT_MAX + 1)}),
            ("path length", {**top, "path": ["q"] + path}),
            ("path entry", {**top, "path": ["q" * (EL_TEXT_MAX + 1)] + path[1:]}),
            ("path entry empty", {**top, "path": [""] + path[1:]}),
            ("impl hi", {**top, "impl": {"file": "a.py", "lo": 1, "hi": EL_LINE_MAX + 1}}),
            ("impl lo zero", {**top, "impl": {"file": "a.py", "lo": 0, "hi": 1}}),
            ("impl lo negative", {**top, "impl": {"file": "a.py", "lo": -3, "hi": 1}}),
            ("impl float", {**top, "impl": {"file": "a.py", "lo": 1.5, "hi": 2}}),
            ("impl missing hi", {**top, "impl": {"file": "a.py", "lo": 1}}),
        ):
            with self.subTest(name):
                self.assertEqual(parse_el(bad).reason, "bad_el")

    def test_a_frac_must_be_four_finite_numbers_on_the_page(self):
        """NaN, Infinity, an integer too large for a float, a bool, a text, three numbers and five are bad_el; the
        whole page as integers is kept as floats."""
        for frac in (
            [float("nan"), 0.1, 0.2, 0.2],
            [0.1, float("inf"), 0.2, 0.2],
            [0.1, 0.1, 10**400, 0.2],
            [True, 0.1, 0.2, 0.2],
            [0.1, 0.1, "0.2", 0.2],
            [0.1, 0.1, 0.2],
            [0.1, 0.1, 0.2, 0.2, 0.2],
            "0.1,0.1,0.2,0.2",
            [-0.1, 0.1, 0.2, 0.2],
        ):
            with self.subTest(frac=frac):
                self.assertEqual(parse_el({**GOOD, "frac": frac}).reason, "bad_el")
        self.assertEqual(parse_el({**GOOD, "frac": [0, 0, 1, 1]}).frac, (0.0, 0.0, 1.0, 1.0))


class FigurePins(Base):
    """A LaTeX document ms and figure document fig with build BUILD1 on screen."""

    def setUp(self):
        """The two documents; the figure's first build."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())

    def post_pin(self, body):
        """POST /api/pin through the handler; (status, parsed body)."""
        code, _, out = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        return code, json.loads(out)

    def post_pin_action(self, pid, action, body=None):
        """POST /api/pins/{pid}/{action} as the local agent; (status, parsed body)."""
        code, _, out = split_resp(self.talk(jreq("POST", "/api/pins/%d/%s" % (pid, action), body or {})))
        return code, json.loads(out)

    def stored_el_text(self, pid):
        """The stored line of pin pid, and its el as text - el_text of the parsed record's el, which is the stored form
        re-serialised (not the raw characters between the keys). The line itself is returned raw, so a test that
        compares lines sees any byte the store changed."""
        for line in ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec["id"] == pid:
                return line, el_text(rec["el"])
        raise AssertionError("pin %d is not stored" % pid)

    def test_a_figure_document_takes_line_pins_and_serves_snippets(self):
        """takes_line_pins, so not view-only; GET /api/snippet reads the script."""
        self.assertTrue(self.fig.takes_line_pins)
        self.assertFalse(self.fig.view_only)
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=fig&file=%s&lo=88&hi=89" % SCRIPT)))
        self.assertEqual(code, 200, body)
        self.assertIn("step_089", json.loads(body)["snippet"])

    def test_a_pin_from_a_map_pick_stores_its_lines_and_element(self):
        """The saved pin is a line pin on the script with the pick's el, scope el, kind el:MonthCell and via map; its
        anchor skips the # comment that opens the range; the store trusts the record."""
        rec = self.pin(pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "글자를 키워 줘"))
        self.assertEqual(
            (rec["doc"], rec["lo"], rec["hi"], rec["scope"], rec["kind"], rec["via"], rec["file_rel"]),
            ("fig", 88, 95, "el", "el:MonthCell", "map", SCRIPT),
        )
        self.assertEqual((rec["el"]["id"], rec["el"]["frac"]), ("B2/calendar/m07", [0.47, 0.18, 0.07, 0.12]))
        self.assertEqual(
            rec["anchor"], {"head": "step_089 = draw(89)", "tail": "step_095 = draw(95)", "head_off": 1, "tail_off": 0}
        )
        self.assertTrue(fits(rec))

    def test_a_region_pin_on_a_figure_carries_the_element(self):
        """An element drawn without code is pinned as a region with its el; no file, no lines."""
        rec = self.pin(pin_from_pick(self.fig, AUGUST_BOX, BOB_ACTOR, "색을 바꿔 줘"))
        self.assertEqual((rec["kind"], rec["el"]["id"]), ("region", "B2/calendar/m08"))
        self.assertNotIn("file", rec)
        self.assertTrue(fits(rec))

    def test_the_region_pin_refusals_do_not_call_a_figure_document_view_only(self):
        """Lines sent with a region pin of a figure document are refused no_source_lines, and neither that sentence nor
        the one for an edit's lines says view-only: the figure document is not view-only. The reason codes stay."""
        facts = ps.APP.document_facts(self.fig)
        self.assertFalse(facts.view_only)
        refused = parse_region({"lo": 1, "page": 1, "frac": [0.1, 0.1, 0.2, 0.2]}, facts)
        self.assertIsInstance(refused, InputRejected)
        self.assertEqual(refused.reason, "no_source_lines")
        self.assertIn("lo", refused.message)
        self.assertNotIn("보기 전용", refused.message)
        self.assertNotIn("보기 전용", REGION_EDIT_REFUSAL)

    def test_an_agent_curl_without_el_routes_by_file_and_is_a_plain_line_pin(self):
        """No doc, no el: the file under figs/ routes the pin to the figure document, where it is a plain line pin."""
        code, d = self.post_pin({"file": SCRIPT, "lo": 20, "hi": 22, "note": "선 굵기"})
        self.assertEqual(code, 200, d)
        rec = self.pin(d["id"])
        self.assertEqual((rec["doc"], rec["kind"], rec["lo"], rec["hi"]), ("fig", "lines", 20, 22))
        self.assertNotIn("el", rec)

    def test_el_is_not_kept_on_a_latex_document(self):
        """el means nothing on a LaTeX document: dropped like an unknown field."""
        pin = add_pin({"doc": "ms", "file": str(self.main), "lo": 4, "hi": 5, "el": GOOD}, dict(LOCAL_ACTOR))
        self.assertNotIn("el", self.pin(pin.core.pid))

    def test_a_malformed_el_on_a_latex_document_is_ignored_not_refused(self):
        """The el parse runs only on a document with an element map: a LaTeX document's body is checked as it always
        was, so an el that would be bad_el on a figure is dropped with the other unknown fields."""
        code, d = self.post_pin({"doc": "ms", "file": str(self.main), "lo": 4, "hi": 5, "el": "B2"})
        self.assertEqual(code, 200, d)
        self.assertNotIn("el", self.pin(d["id"]))

    def test_el_is_not_kept_on_a_view_only_pdf_document(self):
        """A region pin on a view-only PDF document drops an el, well-formed or not, like any unknown field."""
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        rv = Doc("rv", "리뷰", "pdf", self.src, self.src / "review.pdf", paths=ps.APP.C.paths)
        ps.APP.set_docs([*ps.APP.docs, rv])
        for el in (GOOD, "B2"):
            with self.subTest(el=el):
                code, d = self.post_pin({"doc": "rv", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "el": el})
                self.assertEqual(code, 200, d)
                self.assertNotIn("el", self.pin(d["id"]))

    def test_a_malformed_el_is_refused_and_nothing_is_stored(self):
        """On a line pin and on a region pin: 400 bad_el, and pins.jsonl stays empty."""
        line = {"doc": "fig", "file": SCRIPT, "lo": 88, "hi": 95}
        region = {"doc": "fig", "page": 1, "frac": [0.55, 0.18, 0.07, 0.12]}
        for base in (line, region):
            for bad in ("B2", {**GOOD, "path": ["B2"]}, {**GOOD, "impl": {"file": "../x.py", "lo": 1, "hi": 2}}):
                with self.subTest(base=base, bad=bad):
                    code, d = self.post_pin({**base, "el": bad})
                    self.assertEqual((code, d["reason"]), (400, "bad_el"))
        self.assertEqual(ps.APP.read_pins()[0], [])

    def test_every_malformed_el_of_the_boundary_is_refused_over_http(self):
        """The refusals parse_el is tested for, through POST /api/pin: an impl.file that climbs, is absolute, has an
        empty or '.' part, a backslash or a NUL, more path ids than the limit, lines past the limit and a frac that is
        not finite - each 400 bad_el, and nothing is stored."""
        line = {"doc": "fig", "file": SCRIPT, "lo": 88, "hi": 95}

        def impl(**kw):
            """An el whose impl is {file, lo, hi} with the given overrides."""
            return {**GOOD, "impl": {"file": "lib.py", "lo": 1, "hi": 2, **kw}}

        for name, bad in (
            ("climbs", impl(file="a/../../x.py")),
            ("absolute", impl(file="/x.py")),
            ("empty part", impl(file="a//x.py")),
            ("dot part", impl(file="./x.py")),
            ("backslash", impl(file="a\\x.py")),
            ("nul", impl(file="a\x00x.py")),
            ("too long", impl(file="x" * (EL_FILE_MAX + 1))),
            ("line limit", impl(hi=EL_LINE_MAX + 1)),
            ("deep path", {"id": "e", "path": ["p%d" % i for i in range(EL_PATH_MAX)] + ["e"]}),
            ("frac huge integer", {**GOOD, "frac": [0.1, 0.1, 10**400, 0.2]}),
        ):
            with self.subTest(name):
                code, d = self.post_pin({**line, "el": bad})
                self.assertEqual((code, d["reason"]), (400, "bad_el"))
        self.assertEqual(ps.APP.read_pins()[0], [])

    def test_an_edit_re_places_the_element_and_a_lines_edit_keeps_it(self):
        """loc with the strip's el re-places the pin on the strip; lo/hi keep that el; loc without el drops it."""
        pid = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR)
        strip = {"id": "B2/calendar", "path": ["B2", "B2/calendar"], "label": "달력", "part": "CalendarStrip"}
        loc = {
            "file": SCRIPT,
            "lo": 80,
            "hi": 97,
            "scope": "el2",
            "kind": "el:CalendarStrip",
            "via": "map",
            "el": strip,
        }
        p = record_of(edit_pin(pid, {"loc": loc, "base_rev": self.pin(pid)["rev"]}, dict(ALICE_ACTOR)))
        self.assertEqual((p["lo"], p["hi"], p["el"]), (80, 97, strip))
        p = record_of(edit_pin(pid, {"lo": 81, "hi": 97, "base_rev": p["rev"]}, dict(ALICE_ACTOR)))
        self.assertEqual(p["el"], strip)
        p = record_of(
            edit_pin(pid, {"loc": {"file": SCRIPT, "lo": 20, "hi": 22}, "base_rev": p["rev"]}, dict(ALICE_ACTOR))
        )
        self.assertNotIn("el", p)

    def test_an_edit_that_re_places_with_an_el_stores_the_canonical_element(self):
        """The el a loc carries is parsed once at the boundary: an unknown key is dropped, an integer frac is a float,
        a null label is absent, and the key order is the contract's - only an edit whose loc carries an el writes
        one."""
        pid = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR)
        loc = {"file": SCRIPT, "lo": 88, "hi": 95, "el": json.loads(el_text(ODD_EL))}
        p = record_of(edit_pin(pid, {"loc": loc, "base_rev": self.pin(pid)["rev"]}, dict(ALICE_ACTOR)))
        canonical = {"id": "B2/calendar/m07", "path": ODD_EL["path"], "part": "MonthCell", "frac": [0.0, 0.0, 1.0, 1.0]}
        self.assertEqual(el_text(p["el"]), el_text(canonical))
        self.assertEqual(self.stored_el_text(pid)[1], el_text(canonical))

    def test_an_edit_with_a_malformed_el_is_refused(self):
        """An edit's loc goes through the same parse: bad_el, and the pin is unchanged."""
        pid = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR)
        before = self.pin(pid)
        got = edit_pin(
            pid,
            {"loc": {"file": SCRIPT, "lo": 88, "hi": 95, "el": {"id": 3}}, "base_rev": before["rev"]},
            dict(ALICE_ACTOR),
        )
        self.assertEqual(got.reason, "bad_el")
        self.assertEqual(self.pin(pid), before)

    def test_a_region_edit_replaces_or_drops_the_element(self):
        """A region pin's loc with an el writes it (canonical, as a line pin's); one without drops it."""
        pid = pin_from_pick(self.fig, AUGUST_BOX, BOB_ACTOR)
        loc = {"page": 1, "frac": [0.55, 0.18, 0.07, 0.12], "el": {**GOOD, "label": "8월", "future": 1}}
        p = record_of(edit_pin(pid, {"loc": loc, "base_rev": self.pin(pid)["rev"]}, dict(BOB_ACTOR)))
        self.assertEqual(el_text(p["el"]), el_text({**GOOD, "label": "8월"}))
        bad = edit_pin(pid, {"loc": {**loc, "el": {"id": ""}}, "base_rev": p["rev"]}, dict(BOB_ACTOR))
        self.assertEqual(bad.reason, "bad_el")
        p = record_of(
            edit_pin(pid, {"loc": {"page": 1, "frac": [0.55, 0.18, 0.07, 0.12]}, "base_rev": p["rev"]}, dict(BOB_ACTOR))
        )
        self.assertNotIn("el", p)

    def test_edits_that_keep_the_location_leave_the_stored_el_byte_for_byte(self):
        """A figure pin whose el is not canonical (key order, an integer frac, an unknown key, a null label): a note
        edit, a lo/hi-only range edit, a claim, a reply and a close leave the el in pins.jsonl exactly as it was."""
        pid = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR)
        edit_stored(lambda rows: rows[0].__setitem__("el", json.loads(el_text(ODD_EL))))
        line, want = self.stored_el_text(pid)
        self.assertEqual(want, el_text(ODD_EL))
        self.assertIn('"el": ' + want, line)
        rev = self.pin(pid)["rev"]
        steps = (
            ("note", lambda rev: record_of(edit_pin(pid, {"note": "새 메모", "base_rev": rev}, dict(ALICE_ACTOR)))),
            ("range", lambda rev: record_of(edit_pin(pid, {"lo": 89, "hi": 94, "base_rev": rev}, dict(ALICE_ACTOR)))),
            ("scope", lambda rev: record_of(edit_pin(pid, {"scope": "el2", "base_rev": rev}, dict(ALICE_ACTOR)))),
            ("claim", lambda rev: self.post_pin_action(pid, "claim")[1]["pin"]),
            ("reply", lambda rev: self.post_pin_action(pid, "reply", {"text": "확인했습니다"})[1]["pin"]),
            ("close", lambda rev: self.post_pin_action(pid, "close")[1]["pin"]),
        )
        for name, step in steps:
            with self.subTest(step=name):
                after = step(rev)
                rev = after["rev"]
                line, got = self.stored_el_text(pid)
                self.assertEqual(got, want)
                self.assertIn('"el": ' + want, line)
        self.assertEqual((self.pin(pid)["lo"], self.pin(pid)["hi"]), (89, 94))

    def test_a_pin_the_script_moved_under_keeps_its_stored_el_byte_for_byte(self):
        """Lines inserted above the pin move it (anchor re-sync writes lo/hi); the el it names is not part of that move
        and stays exactly as stored."""
        pid = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR)
        edit_stored(lambda rows: rows[0].__setitem__("el", json.loads(el_text(ODD_EL))))
        script = self.fig.src / "src" / "B2_calendar.py"
        script.write_text("# new first line\n" + script.read_text(encoding="utf-8"), encoding="utf-8")
        moved = self.pin(pid)
        self.assertEqual((moved["lo"], moved["hi"]), (89, 96))
        self.assertEqual(self.stored_el_text(pid)[1], el_text(ODD_EL))


if __name__ == "__main__":
    unittest.main()

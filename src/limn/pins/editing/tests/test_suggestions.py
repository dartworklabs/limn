"""Suggested edits through pin creation and editing (docs/adr/0020-suggested-edit-pins.md D1, D2).

First the shape a request sends (parse_suggest and the edit body parser), then the pure editing rules that refuse or
accept a suggestion on the lines it would replace (check_suggestion, decide_new_suggestion, decide_edit) and the
records they write (new_line_pin, evolve_edit), then POST /api/pin and POST /api/pins/{id}/edit over a real server
and state folder: what is stored, what is answered, and that a refusal writes nothing.

Run: uv run pytest -q src/limn/pins/editing/tests/test_suggestions.py
"""

import json
import unittest

from hypothesis import given, strategies as st

from limn.pins.editing.fields import SUGGEST_REFUSAL, parse_suggest
from limn.pins.editing.input import parse_edit
from limn.pins.editing.rules import (
    AddRequest,
    Anchoring,
    ClosedPinReshaped,
    EditBaseChanged,
    EditRequest,
    LinePlace,
    PinEdited,
    PinOutsideTree,
    RegionPlace,
    RemoveSuggestion,
    StaleEdit,
    SuggestBaseChanged,
    SuggestFacts,
    SuggestNoop,
    SuggestRangeTooLong,
    SuggestTextTooLong,
    SuggestUnsupported,
    check_suggestion,
    decide_edit,
    decide_new_suggestion,
    evolve_edit,
    new_line_pin,
    new_region_pin,
)
from limn.pins.editing.values import SUGGEST_LINES_MAX, SUGGEST_MAX
from limn.pins.model import DonePin, OpenPin, ReviewPin
from limn.pins.suggestion import Suggestion
from limn.runtime.documents import Doc
from limn.web.errors import InputRejected

from helpers import TEX, Base, jreq, ps, req, split_resp
from helpers_figure import BUILD1, SCRIPT, b2_map, figure_doc, script_lines, write_build
from helpers_pin_rules import ALICE_PERSON, AT

LINES = tuple(TEX.splitlines())  # main.tex of the server fixture: lines 4-5 are the first paragraph
FIRST_PARAGRAPH = "First paragraph line one about rarewordalpha.\nFirst paragraph line two."
BODY = "Body line seven betaunique.\nBody line eight gammaunique."  # lines 8-9


def line_place(lo=4, hi=5):
    """A line place on main.tex lines lo..hi."""
    return LinePlace(
        {"file": "/ms/main.tex", "name": "main.tex", "lo": lo, "hi": hi, "page": 1},
        frozenset({"file", "lo", "hi", "page"}),
    )


REGION = RegionPlace({"pdf": "/ms/r.pdf", "name": "r.pdf", "kind": "region", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2]})


def open_pin(**extra):
    """An open line pin on main.tex lines 4-5 at rev 2, with whatever extra stored fields are given."""
    return OpenPin.from_record({"id": 3, "file": "/ms/main.tex", "lo": 4, "hi": 5, "note": "n", "rev": 2, **extra})


def decide(pin, request, count=None, facts=None):
    """decide_edit by Alice at AT with clock 10:00 and the note limit of 4000."""
    return decide_edit(pin, request, ALICE_PERSON, AT, "10:00", count, 4000, facts)


def latex_facts(lines=LINES):
    """The facts the shell reads for a LaTeX pin whose file holds lines."""
    return SuggestFacts(True, tuple(lines))


class ParseSuggest(unittest.TestCase):
    """parse_suggest: the shape of a suggestion as a request sends it."""

    def test_string_base_and_text_are_a_suggestion_without_carriage_returns(self):
        """Both strings come over, every CR removed; an empty text (delete the lines) is a suggestion too."""
        self.assertEqual(parse_suggest({"base": "a\r\nb", "text": "c\rd"}), Suggestion("a\nb", "cd"))
        self.assertEqual(parse_suggest({"text": "", "base": "a"}), Suggestion("a", ""))

    def test_every_other_shape_is_bad_suggest(self):
        """Not an object, a missing or an extra key, a value that is not a string: 400 bad_suggest with the one
        sentence of that refusal."""
        for bad in (
            "a",
            ["a", "b"],
            {},
            {"base": "a"},
            {"text": "b"},
            {"base": "a", "text": "b", "note": "x"},
            {"base": 1, "text": "b"},
            {"base": "a", "text": None},
            {"base": ["a"], "text": "b"},
        ):
            with self.subTest(bad=bad):
                self.assertEqual(parse_suggest(bad), InputRejected(SUGGEST_REFUSAL, "bad_suggest"))

    @given(
        st.recursive(
            st.none() | st.booleans() | st.integers() | st.text(),
            lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3),
            max_leaves=8,
        )
        | st.fixed_dictionaries({"base": st.text(), "text": st.text()})
    )
    def test_any_json_value_is_a_suggestion_or_bad_suggest(self, v):
        """Any JSON value parses to a suggestion holding the sent strings without CR, or to bad_suggest - never an
        exception and never another refusal."""
        got = parse_suggest(v)
        if isinstance(got, Suggestion):
            self.assertEqual((got.base, got.text), (v["base"].replace("\r", ""), v["text"].replace("\r", "")))
        else:
            self.assertEqual(got.reason, "bad_suggest")


class EditBody(unittest.TestCase):
    """parse_edit: suggest sets, removes or leaves the suggestion, and needs base_rev like the other fields."""

    def test_an_object_sets_null_removes_and_absence_leaves(self):
        """{base, text} is a Suggestion, null a RemoveSuggestion, no key None - the other fields as before."""
        sets = parse_edit({"suggest": {"base": "a", "text": "b"}, "base_rev": 1}, ())
        self.assertEqual(sets.request.suggest, Suggestion("a", "b"))
        self.assertEqual(parse_edit({"suggest": None, "base_rev": 1}, ()).request.suggest, RemoveSuggestion())
        self.assertIsNone(parse_edit({"note": "x", "base_rev": 1}, ()).request.suggest)

    def test_a_suggestion_alone_is_something_to_change(self):
        """An edit that only sets or removes a suggestion is not nothing_to_change."""
        for suggest in ({"base": "a", "text": "b"}, None):
            with self.subTest(suggest=suggest):
                self.assertNotIsInstance(parse_edit({"suggest": suggest, "base_rev": 1}, ()), InputRejected)

    def test_a_suggestion_change_needs_base_rev_even_beside_a_note_append(self):
        """A note_append may leave base_rev out; a suggestion change may not, alone or with a note_append."""
        for body in ({"suggest": {"base": "a", "text": "b"}}, {"suggest": None, "note_append": "x"}):
            with self.subTest(body=body):
                self.assertEqual(parse_edit(body, ()).reason, "base_rev_required")
        self.assertNotIsInstance(parse_edit({"note_append": "x"}, ()), InputRejected)

    def test_a_malformed_suggestion_is_refused_before_base_rev_is_asked_for(self):
        """bad_suggest is a field check, so it comes before the missing base_rev, as the other fields' do."""
        self.assertEqual(parse_edit({"suggest": "text"}, ()).reason, "bad_suggest")


class CheckSuggestion(unittest.TestCase):
    """check_suggestion: the rules a suggestion keeps on its own, in their order."""

    def test_only_a_latex_documents_line_pin_takes_one(self):
        """Another document kind, or a pin without lines, is unsupported - before any limit is looked at."""
        big = Suggestion("a" * (SUGGEST_MAX + 1), "a" * (SUGGEST_MAX + 1))
        self.assertEqual(check_suggestion(big, (1, 200), False), SuggestUnsupported())
        self.assertEqual(check_suggestion(big, None, True), SuggestUnsupported())

    def test_the_range_may_span_eighty_lines_and_no_more(self):
        """80 lines pass; 81 are too long, with the count and the limit; the range is checked before the texts."""
        ok = Suggestion("a", "b")
        self.assertIsNone(check_suggestion(ok, (1, SUGGEST_LINES_MAX), True))
        self.assertEqual(
            check_suggestion(Suggestion("a", "a"), (5, 5 + SUGGEST_LINES_MAX), True),
            SuggestRangeTooLong(SUGGEST_LINES_MAX + 1, SUGGEST_LINES_MAX),
        )

    def test_base_and_text_may_hold_sixteen_thousand_characters_each(self):
        """At the limit both pass; one past it is too long, the base reported before the text."""
        at = "x" * SUGGEST_MAX
        self.assertIsNone(check_suggestion(Suggestion(at, at[:-1] + "y"), (1, 1), True))
        over = at + "x"
        self.assertEqual(
            check_suggestion(Suggestion(over, over), (1, 1), True),
            SuggestTextTooLong("base", SUGGEST_MAX + 1, SUGGEST_MAX),
        )
        self.assertEqual(
            check_suggestion(Suggestion("a", over), (1, 1), True),
            SuggestTextTooLong("text", SUGGEST_MAX + 1, SUGGEST_MAX),
        )

    def test_a_text_equal_to_its_base_changes_nothing(self):
        """text == base is a no-op; an empty text against a non-empty base deletes and is accepted."""
        self.assertEqual(check_suggestion(Suggestion("a\nb", "a\nb"), (1, 2), True), SuggestNoop())
        self.assertIsNone(check_suggestion(Suggestion("a\nb", ""), (1, 2), True))


class NewPinSuggestion(unittest.TestCase):
    """decide_new_suggestion: a new pin's suggestion against the snapshot its anchor is taken from."""

    def test_a_base_that_is_the_lines_is_accepted(self):
        """Lines 4-5 read as the base: the suggestion is the answer."""
        s = Suggestion(FIRST_PARAGRAPH, "One paragraph line.")
        self.assertEqual(decide_new_suggestion(s, line_place(), True, LINES), s)

    def test_a_base_written_against_other_text_is_refused_with_what_the_lines_read(self):
        """The lines changed under the author: SuggestBaseChanged carries what they read now."""
        s = Suggestion("First paragraph line one.\nFirst paragraph line two.", "x")
        self.assertEqual(decide_new_suggestion(s, line_place(), True, LINES), SuggestBaseChanged(FIRST_PARAGRAPH))

    def test_a_file_that_cannot_be_read_never_matches(self):
        """An empty or unreadable file (no lines) refuses even an empty base, with an empty current."""
        self.assertEqual(
            decide_new_suggestion(Suggestion("", "new line"), line_place(1, 1), True, []), SuggestBaseChanged("")
        )

    def test_a_region_place_or_another_document_is_unsupported(self):
        """A region pin and a line pin outside a LaTeX document cannot carry one."""
        s = Suggestion(FIRST_PARAGRAPH, "x")
        self.assertEqual(decide_new_suggestion(s, REGION, True, LINES), SuggestUnsupported())
        self.assertEqual(decide_new_suggestion(s, line_place(), False, LINES), SuggestUnsupported())


class EditSuggestion(unittest.TestCase):
    """decide_edit with a suggestion: closed pins, stale editors, the range after the edit, and the file."""

    def test_a_closed_pin_refuses_setting_and_removing_a_suggestion(self):
        """Awaiting review or done: any suggestion change is a reshaping edit (409 done), even with base_rev right."""
        for closed in (
            ReviewPin.from_record({**open_pin().record, "done": True, "review": True}),
            DonePin.from_record({**open_pin().record, "done": True}),
        ):
            for change in (Suggestion(FIRST_PARAGRAPH, "x"), RemoveSuggestion()):
                with self.subTest(closed=type(closed).__name__, change=change):
                    got = decide(closed, EditRequest(base_rev=2, suggest=change), facts=latex_facts())
                    self.assertEqual(got, ClosedPinReshaped(closed))

    def test_a_stale_base_rev_is_a_conflict_before_the_suggestion_is_looked_at(self):
        """base_rev 1 on a pin at rev 2: StaleEdit, even though the suggestion would be refused too."""
        pin = open_pin()
        got = decide(pin, EditRequest(base_rev=1, suggest=Suggestion("x", "x")), facts=latex_facts())
        self.assertEqual(got, StaleEdit(pin))

    def test_the_base_is_compared_with_the_range_after_the_edits_own_move(self):
        """lo/hi 8-9 with a base of lines 8-9 is accepted on the moved range; a base of the old lines 4-5 is not."""
        pin = open_pin()
        moved = decide(pin, EditRequest(base_rev=2, lo=8, hi=9, suggest=Suggestion(BODY, "x")), 20, latex_facts())
        self.assertIsInstance(moved, PinEdited)
        self.assertEqual((moved.lines, moved.suggest), ((8, 9), Suggestion(BODY, "x")))
        stale_base = decide(
            pin, EditRequest(base_rev=2, lo=8, hi=9, suggest=Suggestion(FIRST_PARAGRAPH, "x")), 20, latex_facts()
        )
        self.assertEqual(stale_base, EditBaseChanged(pin, BODY))

    def test_a_line_re_placement_is_compared_on_its_own_lines(self):
        """loc placing the pin on lines 8-9 checks the base against those lines."""
        got = decide(
            open_pin(),
            EditRequest(base_rev=2, place=line_place(8, 9), suggest=Suggestion(BODY, "y")),
            None,
            latex_facts(),
        )
        self.assertIsInstance(got, PinEdited)

    def test_a_pin_whose_file_is_outside_the_tree_cannot_take_one(self):
        """No lines could be read (facts.lines None): pin_outside_manuscript, as a lo/hi edit there is."""
        got = decide(
            open_pin(),
            EditRequest(base_rev=2, suggest=Suggestion(FIRST_PARAGRAPH, "x")),
            None,
            SuggestFacts(True, None),
        )
        self.assertEqual(got, PinOutsideTree())

    def test_a_region_pin_or_another_document_is_unsupported(self):
        """A region pin's edit and a line pin of a figure or view-only document refuse a suggestion."""
        region = OpenPin.from_record({"id": 4, "pdf": "/ms/r.pdf", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "rev": 0})
        s = Suggestion(FIRST_PARAGRAPH, "x")
        self.assertEqual(
            decide(region, EditRequest(base_rev=0, suggest=s), facts=SuggestFacts(True, None)), SuggestUnsupported()
        )
        self.assertEqual(
            decide(open_pin(), EditRequest(base_rev=2, suggest=s), facts=SuggestFacts(False, LINES)),
            SuggestUnsupported(),
        )

    def test_removing_needs_no_file_and_setting_without_facts_is_a_defect(self):
        """suggest null is accepted without any read; a suggestion decided without the shell's facts raises."""
        removed = decide(open_pin(), EditRequest(base_rev=2, suggest=RemoveSuggestion()))
        self.assertEqual(removed.suggest, RemoveSuggestion())
        with self.assertRaises(ValueError):
            decide(open_pin(), EditRequest(base_rev=2, suggest=Suggestion(FIRST_PARAGRAPH, "x")))


def edited(pin, **fields):
    """evolve_edit of an accepted fact by Alice at AT with the given changes, nothing re-anchored."""
    base = dict(note=None, place=None, lines=None, range_changed=False, scope=None, kind=None, kind_req=None)
    base.update(fields)
    return evolve_edit(pin, PinEdited(ALICE_PERSON, AT, assignee=None, **base), None, None, None, None)


class EditRecord(unittest.TestCase):
    """evolve_edit and new_line_pin: where suggest is written, kept and removed."""

    def test_setting_appends_replacing_keeps_its_place_and_removing_drops_it(self):
        """A new suggest goes after the existing fields; a replacement stays where the old one was; null removes."""
        pin = open_pin()
        first = edited(pin, suggest=Suggestion("a", "b"))
        self.assertEqual(first.record["suggest"], {"base": "a", "text": "b"})
        keys = list(first.record)
        again = edited(first, suggest=Suggestion("a", "c"))
        self.assertEqual(list(again.record), keys)
        self.assertEqual(again.record["suggest"], {"base": "a", "text": "c"})
        self.assertNotIn("suggest", edited(again, suggest=RemoveSuggestion()).record)

    def test_a_range_edit_without_a_suggestion_keeps_the_stored_one_byte_for_byte(self):
        """A lo/hi move and a line re-placement leave suggest as stored, an unknown nested key included."""
        stored = {"base": FIRST_PARAGRAPH, "text": "x", "later": {"k": [1, 2]}}
        pin = open_pin(suggest=stored)
        self.assertEqual(edited(pin, lines=(8, 9), range_changed=True).record["suggest"], stored)
        self.assertEqual(edited(pin, place=line_place(8, 9), range_changed=True).record["suggest"], stored)

    def test_a_new_line_pins_suggestion_is_its_last_field(self):
        """new_line_pin writes the request's suggestion after every other field; without one there is no key."""
        place = line_place()
        anchoring = Anchoring({"head": "First paragraph line one about rarewordalpha."}, 1.0)
        args = (3, AT, {"login": "local", "name": "agent"}, (), anchoring, "pages", "main", None)
        rec = new_line_pin(place, AddRequest(place, "", suggest=Suggestion(FIRST_PARAGRAPH, "x")), *args).record
        self.assertEqual(list(rec)[-1], "suggest")
        self.assertNotIn("suggest", new_line_pin(place, AddRequest(place, ""), *args).record)

    def test_a_region_pin_with_a_suggestion_is_a_defect(self):
        """The shell refuses first (decide_new_suggestion); building such a region record raises."""
        with self.assertRaises(ValueError):
            new_region_pin(REGION, AddRequest(REGION, "", suggest=Suggestion("a", "b")), 3, AT, {}, (), "pages", "rv")


class SuggestOverHttp(Base):
    """POST /api/pin and POST /api/pins/{id}/edit with a suggestion, through the handler on the fixture main.tex."""

    def setUp(self):
        """The fixture manuscript plus long.tex, 100 numbered lines, for the range limit."""
        super().setUp()
        self.long = self.src / "long.tex"
        self.long.write_text("".join("line %d\n" % n for n in range(1, 101)), encoding="utf-8")

    def post(self, path, body):
        """POST path with a JSON body as the local agent: (status, parsed body)."""
        code, _, out = split_resp(self.talk(jreq("POST", path, body)))
        return code, json.loads(out)

    def get_pin(self, pid):
        """GET /api/pins/{pid}'s pin."""
        code, _, out = split_resp(self.talk(req("GET", "/api/pins/%d" % pid)))
        self.assertEqual(code, 200, out)
        return json.loads(out)["pin"]

    def stored_bytes(self):
        """pins.jsonl and pins.seq as they are on disk now (b'' when missing)."""
        files = (ps.APP.C.pins_jsonl, ps.APP.C.state / "pins.seq")
        return tuple(f.read_bytes() if f.exists() else b"" for f in files)

    def test_a_new_pin_stores_its_suggestion_without_carriage_returns_and_reads_ready(self):
        """A CRLF base and text are stored with plain newlines, last in the record; GET answers suggest_state ready,
        as the last field."""
        base = FIRST_PARAGRAPH.replace("\n", "\r\n")
        code, d = self.post(
            "/api/pin",
            {"file": str(self.main), "lo": 4, "hi": 5, "note": "", "suggest": {"base": base, "text": "One.\r\nTwo."}},
        )
        self.assertEqual(code, 200, d)
        rec = self.pin(d["id"])
        self.assertEqual(rec["suggest"], {"base": FIRST_PARAGRAPH, "text": "One.\nTwo."})
        self.assertEqual(list(rec)[-1], "suggest")
        shown = self.get_pin(d["id"])
        self.assertEqual((shown["suggest_state"], list(shown)[-1]), ("ready", "suggest_state"))

    def test_a_new_pins_base_that_is_not_the_file_is_409_with_current_and_writes_nothing(self):
        """409 suggest_base_changed with the lines' current text; pins.jsonl and pins.seq stay as they were, so the
        next pin takes the id the refused one would have."""
        first = self.add()
        before = self.stored_bytes()
        code, d = self.post(
            "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5, "suggest": {"base": "old text", "text": "x"}}
        )
        self.assertEqual((code, d["reason"], d["current"]), (409, "suggest_base_changed", FIRST_PARAGRAPH))
        self.assertNotIn("pin", d)
        self.assertEqual(self.stored_bytes(), before)
        self.assertEqual(self.add(), first + 1)

    def test_the_limits_and_the_no_op_are_400_and_write_nothing(self):
        """81 lines and a 16,001-character text are suggest_too_long, text == base suggest_noop, a wrong shape
        bad_suggest; nothing is stored for any of them."""
        lines81 = "\n".join("line %d" % n for n in range(1, 82))
        for body, reason in (
            (
                {"file": str(self.long), "lo": 1, "hi": 81, "suggest": {"base": lines81, "text": "x"}},
                "suggest_too_long",
            ),
            (
                {"file": str(self.main), "lo": 4, "hi": 5, "suggest": {"base": FIRST_PARAGRAPH, "text": "y" * 16001}},
                "suggest_too_long",
            ),
            (
                {
                    "file": str(self.main),
                    "lo": 4,
                    "hi": 5,
                    "suggest": {"base": FIRST_PARAGRAPH, "text": FIRST_PARAGRAPH},
                },
                "suggest_noop",
            ),
            ({"file": str(self.main), "lo": 4, "hi": 5, "suggest": {"base": FIRST_PARAGRAPH}}, "bad_suggest"),
        ):
            with self.subTest(reason=reason):
                code, d = self.post("/api/pin", body)
                self.assertEqual((code, d["reason"]), (400, reason), d)
        self.assertEqual(ps.APP.read_pins()[0], [])
        lines80 = "\n".join("line %d" % n for n in range(1, 81))
        code, d = self.post(
            "/api/pin", {"file": str(self.long), "lo": 1, "hi": 80, "suggest": {"base": lines80, "text": ""}}
        )
        self.assertEqual(code, 200, d)

    def test_a_view_only_or_figure_document_refuses_a_suggestion(self):
        """A region pin of a view-only PDF and a line pin of a figure's drawing script: 400 suggest_unsupported, and
        nothing is stored."""
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        fig = figure_doc(self.src, ps.APP.C.paths)
        rv = Doc("rv", "리뷰", "pdf", self.src, self.src / "review.pdf", paths=ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), fig, rv])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(fig, BUILD1, b2_map())
        suggest = {"base": "a", "text": "b"}
        for body in (
            {"doc": "rv", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "suggest": suggest},
            {"doc": "fig", "file": SCRIPT, "lo": 88, "hi": 88, "suggest": suggest},
        ):
            with self.subTest(doc=body["doc"]):
                code, d = self.post("/api/pin", body)
                self.assertEqual((code, d["reason"]), (400, "suggest_unsupported"), d)
        self.assertEqual(ps.APP.read_pins()[0], [])

    def test_an_edit_of_a_figure_pin_refuses_a_suggestion(self):
        """A figure document's line pin is not a LaTeX one: an edit setting a suggestion - even with the script line's
        own text as its base - is 400 suggest_unsupported and the pin is not changed."""
        fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(fig, BUILD1, b2_map())
        code, d = self.post("/api/pin", {"doc": "fig", "file": SCRIPT, "lo": 88, "hi": 88})
        self.assertEqual(code, 200, d)
        pid, before = d["id"], self.stored_bytes()
        line = script_lines()[87]
        code, d = self.post(
            "/api/pins/%d/edit" % pid, {"base_rev": 0, "suggest": {"base": line, "text": line + " # x"}}
        )
        self.assertEqual((code, d["reason"]), (400, "suggest_unsupported"), d)
        self.assertEqual(self.stored_bytes(), before)

    def test_an_edit_sets_replaces_and_removes_a_suggestion(self):
        """Each edit answers the pin with its suggestion and state, and bumps rev; null removes it and the state."""
        pid = self.add()
        code, d = self.post(
            "/api/pins/%d/edit" % pid, {"base_rev": 0, "suggest": {"base": FIRST_PARAGRAPH, "text": "A."}}
        )
        self.assertEqual(code, 200, d)
        self.assertEqual((d["pin"]["suggest"]["text"], d["pin"]["suggest_state"], d["pin"]["rev"]), ("A.", "ready", 1))
        code, d = self.post(
            "/api/pins/%d/edit" % pid, {"base_rev": 1, "suggest": {"base": FIRST_PARAGRAPH, "text": "B."}}
        )
        self.assertEqual((code, d["pin"]["suggest"]["text"]), (200, "B."))
        code, d = self.post("/api/pins/%d/edit" % pid, {"base_rev": 2, "suggest": None})
        self.assertEqual(code, 200, d)
        self.assertNotIn("suggest", d["pin"])
        self.assertNotIn("suggest_state", d["pin"])
        self.assertNotIn("suggest", self.pin(pid))

    def test_an_edits_base_conflict_is_409_with_current_and_the_latest_pin_and_writes_nothing(self):
        """A base the file no longer has: 409 suggest_base_changed with current and the pin as it stands; the stored
        line does not change."""
        pid = self.add()
        before = self.stored_bytes()
        code, d = self.post("/api/pins/%d/edit" % pid, {"base_rev": 0, "suggest": {"base": "old", "text": "new"}})
        self.assertEqual(
            (code, d["reason"], d["current"], d["pin"]["id"]), (409, "suggest_base_changed", FIRST_PARAGRAPH, pid)
        )
        self.assertEqual(self.stored_bytes(), before)

    def test_an_edit_checks_the_base_on_the_range_it_moves_to(self):
        """lo/hi 8-9 with the base of lines 8-9 is stored on the moved pin; with the old range's base it is 409."""
        pid = self.add()
        code, d = self.post(
            "/api/pins/%d/edit" % pid,
            {"base_rev": 0, "lo": 8, "hi": 9, "suggest": {"base": FIRST_PARAGRAPH, "text": "x"}},
        )
        self.assertEqual((code, d.get("current")), (409, BODY))
        code, d = self.post(
            "/api/pins/%d/edit" % pid, {"base_rev": 0, "lo": 8, "hi": 9, "suggest": {"base": BODY, "text": "x"}}
        )
        self.assertEqual((code, d["pin"]["lo"], d["pin"]["suggest_state"]), (200, 8, "ready"))

    def test_a_closed_pin_refuses_a_suggestion_change_with_409_done(self):
        """After a close, setting or removing a suggestion is 409 done with the pin; a note edit still goes through."""
        pid = self.add()
        code, d = self.post("/api/pins/%d/close" % pid, {})
        self.assertEqual(code, 200, d)
        rev = d["pin"]["rev"]
        for suggest in ({"base": FIRST_PARAGRAPH, "text": "x"}, None):
            with self.subTest(suggest=suggest):
                code, d = self.post("/api/pins/%d/edit" % pid, {"base_rev": rev, "suggest": suggest})
                self.assertEqual((code, d["reason"], d["pin"]["id"]), (409, "done", pid))
        code, d = self.post("/api/pins/%d/edit" % pid, {"base_rev": rev, "note": "memo"})
        self.assertEqual(code, 200, d)

    def test_a_range_edit_keeps_the_suggestion_and_its_state_becomes_changed(self):
        """Moving the pin to lines 8-9 without a suggest key keeps the stored suggestion as it was; its state is
        then changed, since lines 8-9 are not its base."""
        pid = self.add()
        self.post("/api/pins/%d/edit" % pid, {"base_rev": 0, "suggest": {"base": FIRST_PARAGRAPH, "text": "x"}})
        code, d = self.post("/api/pins/%d/edit" % pid, {"base_rev": 1, "lo": 8, "hi": 9})
        self.assertEqual(code, 200, d)
        self.assertEqual(
            (d["pin"]["suggest"], d["pin"]["suggest_state"]), ({"base": FIRST_PARAGRAPH, "text": "x"}, "changed")
        )

    def test_the_state_follows_the_file_and_the_pins_place(self):
        """Editing the paragraph makes the state changed; when the pin then loses its place it is unknown."""
        pid = self.add()
        self.post("/api/pins/%d/edit" % pid, {"base_rev": 0, "suggest": {"base": FIRST_PARAGRAPH, "text": "x"}})
        self.main.write_text(TEX.replace("First paragraph line two.", "First paragraph line 2."), encoding="utf-8")
        self.assertEqual(self.get_pin(pid)["suggest_state"], "changed")
        self.main.write_text(TEX.replace("First paragraph line one about rarewordalpha.\n", ""), encoding="utf-8")
        shown = self.get_pin(pid)
        self.assertEqual((shown.get("stale"), shown["suggest_state"]), (True, "unknown"))

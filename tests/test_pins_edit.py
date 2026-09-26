"""limn.pins.edit - the edit rules and the new-pin records, tested directly with records and no store, clock or HTTP.

The HTTP contract of POST /api/pin and /api/pins/{id}/edit (statuses, messages, stored lines, notices) is pinned in
test_server.py and the other version suites; here the pure decisions and records are checked on their own (rule R1).

Run: uv run pytest -q tests/test_pins_edit.py
"""
import unittest

from limn.pins.edit import (
    ASSIGNEE_AGENT, AddRequest, Anchoring, ClosedPinReshaped, EditRequest, LinePlace, Located, NoteTooLong, PinEdited,
    PinOutsideTree, RangeOutsideFile, RegionPlace, StaleEdit, assignment_text, decide_edit, evolve_edit, file_after,
    new_line_pin, new_region_pin,
)
from limn.pins.model import Agent, DonePin, OpenPin, Person, ReviewPin

ALICE = Person("alice@example.com", "Alice Kim", "https://example.com/a.png")
AGENT = Agent("local", "로컬/에이전트")
AT = "2026-09-26 10:00:00"
NOTE_MAX = 2000


def line_record(**extra):
    """A stored line pin at L4-L5 of main.tex, matched by SyncTeX, with one earlier thread entry."""
    record = {"file": "/ms/main.tex", "name": "main.tex", "lo": 4, "hi": 5, "page": 2, "kind": "lines",
              "via": "synctex", "score": 0.7, "frac": [0.1, 0.2, 0.3, 0.4], "note": "old", "id": 3,
              "thread": [{"id": 1, "by": {"login": "bob@example.com", "name": "Bob"}, "at": "t0", "text": "hi"}],
              "anchor": {"head": "x"}, "synced_at": 1.0, "rev": 2}
    record.update(extra)
    return record


def decide(pin, count=None, clock="10:00", **fields):
    """decide_edit() on an EditRequest with the given fields, by Alice at AT."""
    return decide_edit(pin, EditRequest(**fields), ALICE, AT, clock, count, NOTE_MAX)


def edited(**fields):
    """The PinEdited fact for Alice at AT with the given changes; everything else untouched."""
    base = dict(note=None, place=None, lines=None, range_changed=False, scope=None, kind=None, kind_req=None,
                assignee=None)
    base.update(fields)
    return PinEdited(ALICE, AT, **base)


class DecideEdit(unittest.TestCase):
    """What an edit may do, checked before anything changes; refusals are returned values."""

    def test_closed_pin_refuses_reshaping_but_not_note_level_fields(self):
        """A closed pin keeps its place (409 done) - yet its note, kind_req and assignee may still change."""
        for pin in (ReviewPin(line_record(done=True, review=True)), DonePin(line_record(done=True))):
            self.assertEqual(decide(pin, base_rev=2, lo=4), ClosedPinReshaped(pin))
            self.assertEqual(decide(pin, base_rev=2, scope="para"), ClosedPinReshaped(pin))
            self.assertEqual(decide(pin, base_rev=2, place=LinePlace({"file": "/ms/main.tex"}, frozenset())),
                             ClosedPinReshaped(pin))
            self.assertIsInstance(decide(pin, base_rev=2, note="n", kind_req="question", assignee="agent"), PinEdited)

    def test_stale_base_rev_is_a_conflict_checked_after_the_closed_rule(self):
        """A base_rev other than the stored rev is StaleEdit; a missing rev counts as 0."""
        pin = OpenPin(line_record())
        self.assertEqual(decide(pin, base_rev=1, note="n"), StaleEdit(pin))
        self.assertIsInstance(decide(OpenPin(line_record(rev=None)), base_rev=0, note="n"), PinEdited)
        closed = DonePin(line_record(done=True))
        self.assertEqual(decide(closed, base_rev=1, lo=4), ClosedPinReshaped(closed))

    def test_note_append_merges_under_the_note_with_a_stamp(self):
        """note_append needs no base_rev and goes under the stored note - or the one this edit sets - after "(추가 HH:MM)"."""
        pin = OpenPin(line_record())
        self.assertEqual(decide(pin, note_append="more").note, "old\n(추가 10:00) more")
        self.assertEqual(decide(pin, base_rev=2, note="new", note_append="more").note, "new\n(추가 10:00) more")
        self.assertEqual(decide(OpenPin(line_record(note="")), note_append="more").note, "(추가 10:00) more")

    def test_merged_note_over_the_limit_is_refused_with_its_length(self):
        """The merged length is what counts, even when the appended text alone is short."""
        pin = OpenPin(line_record(note="x" * (NOTE_MAX - 5)))
        merged = NOTE_MAX - 5 + 1 + len("(추가 10:00) ") + 3
        self.assertEqual(decide(pin, note_append="yyy"), NoteTooLong(merged, NOTE_MAX))

    def test_lo_hi_needs_a_located_file_and_must_fit_it(self):
        """No line count (file outside the tree) is PinOutsideTree; a range past the file is RangeOutsideFile."""
        pin = OpenPin(line_record())
        self.assertEqual(decide(pin, count=None, base_rev=2, lo=4, hi=6), PinOutsideTree())
        self.assertEqual(decide(pin, count=10, base_rev=2, hi=11), RangeOutsideFile(10, 4, 11))
        self.assertEqual(decide(pin, count=10, base_rev=2, lo=6), RangeOutsideFile(10, 6, 5))
        self.assertEqual(decide(pin, count=0, base_rev=2, lo=1, hi=1).lines, (1, 1))   # an empty file still has line 1

    def test_range_changes_when_moved_or_when_the_pin_was_stale(self):
        """The same lines are no change unless the pin had lost its place; one bound alone keeps the stored other."""
        pin = OpenPin(line_record())
        same = decide(pin, count=10, base_rev=2, lo=4, hi=5)
        self.assertEqual((same.lines, same.range_changed, same.span()), ((4, 5), False, None))
        moved = decide(pin, count=10, base_rev=2, hi=7)
        self.assertEqual((moved.lines, moved.range_changed, moved.span()), ((4, 7), True, (4, 7)))
        stale = decide(OpenPin(line_record(stale=True)), count=10, base_rev=2, lo=4, hi=5)
        self.assertTrue(stale.range_changed)

    def test_a_line_re_placement_always_changes_the_range(self):
        """place replaces the location, so its lines are re-anchored; lo/hi alongside it are ignored."""
        place = LinePlace({"file": "/ms/main.tex", "lo": 8, "hi": 9}, frozenset({"file", "lo", "hi"}))
        event = decide(OpenPin(line_record()), base_rev=2, place=place, lo=1)
        self.assertEqual((event.lines, event.range_changed, event.span()), (None, True, (8, 9)))


class EvolveEdit(unittest.TestCase):
    """How an accepted edit writes the record: in place, keeping field order and the pin's state."""

    def test_line_re_placement_keeps_unnamed_page_and_frac_and_defaults_kind(self):
        """Location fields are replaced as a whole; page/frac the request left out stay, kind falls back to "lines"."""
        record = line_record(scope="raw", quote="q", frac_build="pages")
        place = LinePlace({"file": "/ms/b.tex", "name": "b.tex", "lo": 8, "hi": 9, "page": 1},
                          frozenset({"file", "lo", "hi"}))
        out = evolve_edit(OpenPin(record), edited(place=place, range_changed=True), None, None, None, None).record
        self.assertEqual((out["file"], out["lo"], out["hi"], out["page"], out["frac"], out["kind"]),
                         ("/ms/b.tex", 8, 9, 2, [0.1, 0.2, 0.3, 0.4], "lines"))
        for gone in ("via", "score", "scope", "quote"):
            self.assertNotIn(gone, out)
        self.assertEqual(out["frac_build"], "pages")          # frac was not re-placed, so its build identity stays

    def test_line_re_placement_with_frac_forgets_frac_build_and_takes_scope_and_kind_from_the_request(self):
        """A named frac replaces the stored one and drops the legacy frac_build; scope/kind fill in what place lacks."""
        place = LinePlace({"file": "/ms/main.tex", "lo": 4, "hi": 5, "page": 3, "frac": [0, 0, 1, 1]},
                          frozenset({"file", "lo", "hi", "page", "frac"}))
        out = evolve_edit(OpenPin(line_record(frac_build="pages")),
                          edited(place=place, range_changed=True, scope="para", kind="env"), None, None, None,
                          None).record
        self.assertEqual((out["page"], out["frac"], out["scope"], out["kind"]), (3, [0, 0, 1, 1], "para", "env"))
        self.assertNotIn("frac_build", out)

    def test_region_re_placement_sets_the_region_and_drops_an_unsent_quote(self):
        """A view-only pin's page, frac and pdf_build are replaced; a quote not sent is removed."""
        record = {"pdf": "/ms/r.pdf", "page": 1, "frac": [0, 0, 1, 1], "kind": "region", "quote": "old", "rev": 0}
        place = RegionPlace({"pdf": "/ms/r.pdf", "page": 2, "frac": [0.1, 0.1, 0.2, 0.2], "pdf_build": "pages"})
        out = evolve_edit(OpenPin(record), edited(place=place), None, None, None, None).record
        self.assertEqual((out["page"], out["frac"], out["pdf_build"]), (2, [0.1, 0.1, 0.2, 0.2], "pages"))
        self.assertNotIn("quote", out)

    def test_moved_lines_forget_matching_and_take_the_new_anchor(self):
        """A moved range drops via/score; the shell's anchor and synced_at replace the old ones and clear stale/sync."""
        pin = OpenPin(line_record(stale=True, sync="lost"))
        out = evolve_edit(pin, edited(lines=(4, 7), range_changed=True), Located("/ms/main.tex", "main.tex"),
                          Anchoring({"head": "y"}, 9.5), None, None).record
        self.assertEqual((out["lo"], out["hi"], out["anchor"], out["synced_at"], out["file_rel"]),
                         (4, 7, {"head": "y"}, 9.5, "main.tex"))
        for gone in ("via", "score", "stale", "sync"):
            self.assertNotIn(gone, out)

    def test_unmoved_lines_keep_matching_fields(self):
        """Writing the same lo/hi keeps via/score: the range is still the matching result."""
        out = evolve_edit(OpenPin(line_record()), edited(lines=(4, 5)), None, None, None, None).record
        self.assertEqual((out["via"], out["score"]), ("synctex", 0.7))

    def test_note_mentions_and_note_level_fields_then_edit_stamp_and_rev(self):
        """note, kind_req and the note's @-tags are written; an empty tag list drops mentions; rev goes up by one."""
        pin = DonePin(line_record(done=True, mentions=["bob@example.com"]))
        out = evolve_edit(pin, edited(note="new", kind_req="question"), None, None, (), None)
        self.assertIsInstance(out, DonePin)
        self.assertEqual((out.record["note"], out.record["kind_req"], out.record["rev"]), ("new", "question", 3))
        self.assertNotIn("mentions", out.record)
        self.assertEqual((out.record["edited_at"], out.record["edited_by"]),
                         (AT, {"login": ALICE.login, "name": ALICE.name}))
        tagged = evolve_edit(OpenPin(line_record()), edited(note="@Bob"), None, None, ["bob@example.com"], None)
        self.assertEqual(tagged.record["mentions"], ["bob@example.com"])
        untouched = evolve_edit(OpenPin(line_record(mentions=["x"])), edited(kind_req="fix"), None, None, None, None)
        self.assertEqual(untouched.record["mentions"], ["x"])

    def test_a_changed_assignee_leaves_an_assign_entry(self):
        """A new assignee is recorded with an ev=assign thread entry by the editor; the same assignee changes nothing."""
        out = evolve_edit(OpenPin(line_record()), edited(assignee="bob@example.com"), None, None, None, "Bob Park").record
        self.assertEqual(out["assignee"], "bob@example.com")
        self.assertEqual(out["thread"][-1], {"id": 2, "by": {"login": ALICE.login, "name": ALICE.name, "pic": ALICE.pic},
                                             "at": AT, "text": "담당: @Bob Park", "ev": "assign"})
        same = evolve_edit(OpenPin(line_record(assignee="agent")), edited(assignee="agent"), None, None, None, None)
        self.assertEqual(len(same.record["thread"]), 1)

    def test_new_fields_go_to_the_end_in_the_stores_order(self):
        """Fields already stored keep their position; file_rel, kind_req, edited_* follow in the old write order."""
        record = {"id": 1, "file": "/ms/main.tex", "lo": 4, "hi": 5, "note": "a", "rev": 0}
        out = evolve_edit(OpenPin(record), edited(note="b", kind_req="fix"), Located("/ms/main.tex", "main.tex"), None,
                          (), None).record
        self.assertEqual(list(out), ["id", "file", "lo", "hi", "note", "rev", "file_rel", "kind_req", "edited_at",
                                     "edited_by"])


class Helpers(unittest.TestCase):
    """The small rules the shell leans on."""

    def test_file_after_takes_a_line_places_file_and_keeps_file_rel(self):
        """Only a line re-placement changes the file the shell locates; file_rel always goes along."""
        record = line_record(file_rel="main.tex")
        place = LinePlace({"file": "/ms/b.tex"}, frozenset({"file"}))
        self.assertEqual(file_after(record, EditRequest(place=place)), {"file": "/ms/b.tex", "file_rel": "main.tex"})
        self.assertEqual(file_after(record, EditRequest(note="n")), {"file": "/ms/main.tex", "file_rel": "main.tex"})
        region = RegionPlace({"page": 1})
        self.assertEqual(file_after({"pdf": "/r.pdf"}, EditRequest(place=region)), {"file": None, "file_rel": None})

    def test_assignment_text_names_the_agent_or_the_person(self):
        """The agent is "에이전트"; a person is @name, or @login when the name is unknown."""
        self.assertEqual(assignment_text(ASSIGNEE_AGENT, None), "담당: 에이전트")
        self.assertEqual(assignment_text("bob@example.com", "Bob Park"), "담당: @Bob Park")
        self.assertEqual(assignment_text("bob@example.com", None), "담당: @bob@example.com")

    def test_request_predicates(self):
        """reshapes() is what a closed pin refuses; sets_lines() is a lo/hi edit without a re-placement."""
        self.assertFalse(EditRequest(note="n", kind_req="fix", assignee="agent").reshapes())
        self.assertTrue(EditRequest(kind="env").reshapes())
        self.assertTrue(EditRequest(hi=3).sets_lines())
        self.assertFalse(EditRequest(hi=3, place=LinePlace({}, frozenset())).sets_lines())


class NewPins(unittest.TestCase):
    """The records of new pins, field for field in the order the store has always written them."""

    def test_new_line_pin(self):
        """Location, kind default, note, at, id, author, kind_req, mentions, assignee, anchor, synced_at, pdf_build,
        doc, rev 0, then where the file is (file rewritten in place, file_rel last)."""
        place = LinePlace({"file": "/ms/main.tex", "name": "main.tex", "lo": 4, "hi": 5, "page": 1},
                          frozenset({"file", "lo", "hi"}))
        request = AddRequest(place, "fix @Bob", "question", "bob@example.com")
        pin = new_line_pin(place, request, 7, AT, {"login": "alice@example.com", "name": "Alice"}, ["bob@example.com"],
                           Anchoring({"head": "h"}, 0), "pages", "ms", Located("/ms2/main.tex", "main.tex"))
        self.assertIsInstance(pin, OpenPin)
        self.assertEqual(list(pin.record), ["file", "name", "lo", "hi", "page", "kind", "note", "at", "id", "author",
                                            "kind_req", "mentions", "assignee", "anchor", "synced_at", "pdf_build",
                                            "doc", "rev", "file_rel"])
        self.assertEqual((pin.record["file"], pin.record["kind"], pin.record["id"], pin.record["rev"]),
                         ("/ms2/main.tex", "lines", 7, 0))

    def test_new_line_pin_keeps_a_sent_build_and_kind_and_omits_empty_fields(self):
        """pdf_build the viewer sent wins over the current build; no kind_req, tags or assignee means no such fields."""
        place = LinePlace({"file": "/ms/main.tex", "lo": 4, "hi": 5, "kind": "env", "pdf_build": "pages-1"},
                          frozenset())
        pin = new_line_pin(place, AddRequest(place, ""), 1, AT, {"login": "local"}, (), Anchoring({}, 0), "pages",
                           "ms", None)
        self.assertEqual((pin.record["kind"], pin.record["pdf_build"]), ("env", "pages-1"))
        for absent in ("kind_req", "mentions", "assignee", "file_rel"):
            self.assertNotIn(absent, pin.record)

    def test_new_region_pin(self):
        """A region pin: region fields, note, at, id, author, kind_req, pdf_build, doc, rev 0, then mentions, assignee."""
        place = RegionPlace({"pdf": "/ms/r.pdf", "name": "r.pdf", "kind": "region", "page": 2, "frac": [0, 0, 1, 1]})
        request = AddRequest(place, "n", "fix", ASSIGNEE_AGENT)
        pin = new_region_pin(place, request, 9, AT, {"login": "local"}, ["bob@example.com"], "pages", "rv")
        self.assertEqual(list(pin.record), ["pdf", "name", "kind", "page", "frac", "note", "at", "id", "author",
                                            "kind_req", "pdf_build", "doc", "rev", "mentions", "assignee"])


if __name__ == "__main__":
    unittest.main()

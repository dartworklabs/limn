"""limn.pins.suggestion and where a stored suggestion is trusted and shown - the record check (limn.pins.record), the
model's byte-exact round trip, and the read-time `suggest_state` of limn.pins.listing.projection - tested directly
with values and records, no store, files or HTTP (docs/adr/0020-suggested-edit-pins.md D1, D2).

Run: uv run pytest -q src/limn/pins/tests/test_suggestion.py
"""

import json
import unittest

from hypothesis import given, strategies as st

from limn.pins.listing.projection import pin_view, public_record, suggest_view
from limn.pins.model import parse_pin
from limn.pins.record import Broken, parse_record
from limn.pins.suggestion import (
    Suggestion,
    is_suggest_record,
    lines_text,
    suggest_state,
    suggestion_of,
    without_cr,
)
from limn.runtime.documents import DOC_KEY_RE
from limn.security.people import is_actor

LINES = ["\\section{Intro}", "First line.", "Second line.", "Third line."]
LINE_PIN = {"id": 7, "file": "/ms/main.tex", "lo": 2, "hi": 3, "note": "", "rev": 0}


def stored(r):
    """The store's record check as the server binds it (limn.pins.runtime.PinCommands.parse_record)."""
    return parse_record(r, DOC_KEY_RE.fullmatch, is_actor)


def store_line(r):
    """r as one pins.jsonl line, with the store's json.dumps settings (limn.pins.store.dump_jsonl)."""
    return json.dumps(r, ensure_ascii=False)


class SuggestionValue(unittest.TestCase):
    """The value a parser builds and the rules store."""

    def test_its_record_is_base_then_text(self):
        """to_record is the stored and answered shape: {"base", "text"} in that order."""
        self.assertEqual(list(Suggestion("a", "b").to_record().items()), [("base", "a"), ("text", "b")])

    def test_a_carriage_return_or_a_non_string_cannot_be_built(self):
        """The parsers remove every carriage return; a value still holding one, or holding a non-string, is a defect
        of the caller and raises."""
        for base, text in (("a\r", "b"), ("a", "b\r\n"), (1, "b"), ("a", None)):
            with self.subTest(base=base, text=text), self.assertRaises(ValueError):
                Suggestion(base, text)

    def test_without_cr_drops_every_carriage_return(self):
        """CRLF, a lone CR and a CR inside a line all go; nothing else changes."""
        self.assertEqual(without_cr("a\r\nb\rc\r"), "a\nbc")


class LinesText(unittest.TestCase):
    """lines_text: the lines lo..hi as a base reads them."""

    def test_the_range_is_joined_with_newlines_and_no_trailing_one(self):
        """Lines 2..3 are "First line.\\nSecond line."; one line is itself."""
        self.assertEqual(lines_text(LINES, 2, 3), "First line.\nSecond line.")
        self.assertEqual(lines_text(LINES, 4, 4), "Third line.")

    def test_carriage_returns_in_the_lines_are_removed(self):
        """A line read with its CR kept compares like one without it."""
        self.assertEqual(lines_text(["a\r", "b\r"], 1, 2), "a\nb")

    def test_a_range_outside_the_lines_is_none(self):
        """Past the end, before line 1, backwards, and any range of an empty (or unreadable) file read nothing."""
        for lo, hi, lines in ((4, 5, LINES), (0, 1, LINES), (3, 2, LINES), (1, 1, [])):
            with self.subTest(lo=lo, hi=hi, lines=lines):
                self.assertIsNone(lines_text(lines, lo, hi))


class StoredShape(unittest.TestCase):
    """is_suggest_record and suggestion_of, and the record check that uses the first."""

    def test_a_base_and_a_text_are_a_suggestion_and_unknown_keys_pass(self):
        """Strings base and text are trusted; a key a later version adds passes, as an el's does."""
        self.assertTrue(is_suggest_record({"base": "a", "text": ""}))
        self.assertTrue(is_suggest_record({"base": "a", "text": "b", "later": 1}))
        self.assertEqual(suggestion_of({"text": "b", "base": "a", "later": 1}), Suggestion("a", "b"))

    def test_a_hand_edited_carriage_return_is_removed_when_lifted(self):
        """A stored value with a CR is still read; the lifted suggestion holds none."""
        self.assertEqual(suggestion_of({"base": "a\r\nb", "text": "c\r"}), Suggestion("a\nb", "c"))

    def test_other_shapes_are_not_a_suggestion(self):
        """Not an object, a missing base or text, a non-string one: no suggestion, and never an exception."""
        for v in (
            None,
            "a",
            ["a", "b"],
            {"base": "a"},
            {"text": "b"},
            {"base": 1, "text": "b"},
            {"base": "a", "text": None},
        ):
            with self.subTest(v=v):
                self.assertFalse(is_suggest_record(v))
                self.assertIsNone(suggestion_of(v))

    def test_a_malformed_stored_suggestion_breaks_its_line(self):
        """The record check treats a malformed suggest like a malformed el: the line is broken, not served."""
        for bad in ("a", [], {"base": "a"}, {"base": "a", "text": 2}):
            with self.subTest(bad=bad):
                self.assertIsInstance(stored({**LINE_PIN, "suggest": bad}), Broken)

    def test_a_well_formed_or_null_suggestion_is_trusted(self):
        """A {base, text} and a null (no suggestion) both pass, and so does a record without the field."""
        for r in (LINE_PIN, {**LINE_PIN, "suggest": None}, {**LINE_PIN, "suggest": {"base": "a", "text": "b"}}):
            with self.subTest(r=r):
                self.assertNotIsInstance(stored(r), Broken)

    def test_a_record_with_a_suggestion_is_written_back_byte_for_byte(self):
        """The model keeps suggest among the fields it does not lift: parsed and written back, the line is the same
        bytes, field order and an unknown nested key included."""
        r = {
            "id": 7,
            "file": "/ms/main.tex",
            "suggest": {"base": "First line.\nSecond line.", "text": "고친 줄", "later": {"b": 1, "a": 2}},
            "lo": 2,
            "hi": 3,
            "note": "",
        }
        self.assertEqual(store_line(parse_pin(r).record), store_line(r))


class State(unittest.TestCase):
    """suggest_state: whether a suggestion still fits its lines."""

    def test_the_three_states(self):
        """The lines read as the base: ready; they read otherwise: changed; stale or unread: unknown."""
        s = Suggestion("First line.\nSecond line.", "x")
        self.assertEqual(suggest_state(s, "First line.\nSecond line.", False), "ready")
        self.assertEqual(suggest_state(s, "First line.\nSecond line, edited.", False), "changed")
        self.assertEqual(suggest_state(s, "First line.\nSecond line.", True), "unknown")
        self.assertEqual(suggest_state(s, None, False), "unknown")

    def test_carriage_returns_do_not_make_lines_changed(self):
        """A file that turned CRLF still reads as the base."""
        self.assertEqual(suggest_state(Suggestion("a\nb", "c"), "a\r\nb\r", False), "ready")

    @given(
        st.lists(st.text(alphabet=st.characters(blacklist_characters="\r\n")), min_size=1, max_size=8),
        st.data(),
    )
    def test_a_base_taken_from_the_lines_is_ready_until_they_change(self, lines, data):
        """For any lines and any range in them, a suggestion whose base is lines_text of that range is ready on those
        lines, unknown on a stale pin, and changed once one of its lines gains a character."""
        lo = data.draw(st.integers(1, len(lines)))
        hi = data.draw(st.integers(lo, len(lines)))
        s = Suggestion(lines_text(lines, lo, hi), "replacement")
        self.assertEqual(suggest_state(s, lines_text(lines, lo, hi), False), "ready")
        self.assertEqual(suggest_state(s, lines_text(lines, lo, hi), True), "unknown")
        edited = [*lines]
        edited[lo - 1] += "x"
        self.assertEqual(suggest_state(s, lines_text(edited, lo, hi), False), "changed")


class Projection(unittest.TestCase):
    """suggest_view, public_record and pin_view: where suggest_state is computed and placed."""

    def test_suggest_view_measures_the_records_range(self):
        """Lines 2..3 of the file now decide; no suggestion gives None; an unlocated file or a stale pin unknown."""
        r = {**LINE_PIN, "suggest": {"base": "First line.\nSecond line.", "text": "x"}}
        self.assertEqual(suggest_view(r, LINES), "ready")
        self.assertEqual(suggest_view({**r, "lo": 3, "hi": 4}, LINES), "changed")
        self.assertEqual(suggest_view(r, None), "unknown")
        self.assertEqual(suggest_view({**r, "stale": True}, LINES), "unknown")
        self.assertIsNone(suggest_view(LINE_PIN, LINES))
        self.assertIsNone(suggest_view({**LINE_PIN, "suggest": "bad"}, LINES))

    def test_public_record_puts_the_state_last_and_drops_a_stored_one(self):
        """The edge's state is the last field; a suggest_state left in the stored line is never answered."""
        r = {**LINE_PIN, "suggest_state": "ready", "suggest": {"base": "a", "text": "b"}}
        out = public_record(r, None, "changed")
        self.assertEqual(list(out)[-1], "suggest_state")
        self.assertEqual(out["suggest_state"], "changed")
        self.assertNotIn("suggest_state", public_record(r, None))
        self.assertEqual(out["suggest"], {"base": "a", "text": "b"})

    def test_pin_view_moves_the_state_after_every_computed_field(self):
        """In GET /api/pins the state follows rel, est, doc, state, addressed and fyi, so it is last there too."""
        r = {**LINE_PIN, "suggest": {"base": "a", "text": "b"}}
        rec = pin_view(r, public_record(r, None, "ready"), [], False, "main", 0.0)
        self.assertEqual(list(rec)[-7:], ["rel", "est", "doc", "state", "addressed", "fyi", "suggest_state"])

    def test_a_pin_without_a_suggestion_is_shown_as_before(self):
        """No suggestion, no suggest_state: the answer's fields are exactly those of an older version."""
        self.assertEqual(public_record(LINE_PIN, None), public_record(LINE_PIN, None, None))
        rec = pin_view(LINE_PIN, public_record(LINE_PIN, None), [], False, "main", 0.0)
        self.assertNotIn("suggest_state", rec)

"""limn.pins.record - the store's record check, called directly with the two shapes the composition root passes in.

The check as the store gets it (server.valid_rec, with limn.documents.DOC_KEY_RE and limn.people.is_actor) is driven
end to end in test_server.py and test_v03.py; the purity of the module is in test_pins_lifecycle.py (Purity). Here
the document key and actor rules are stand-ins, so each test also sees that the check asks them - and only them - for
those two shapes.

Run: uv run pytest -q tests/test_pins_record.py
"""

import unittest

from limn.pins.record import THREAD_EVENTS, is_int, valid_rec

ALICE = {"login": "alice@example.com", "name": "Alice Kim"}
LINE = {"id": 3, "file": "/ms/main.tex", "lo": 4, "hi": 5, "note": "fix", "author": ALICE, "at": "2026-09-26 10:00:00"}
REGION = {"id": 4, "pdf": "/ms/review.pdf", "page": 2, "frac": [0.1, 0.2, 0.5, 0.1], "kind": "region", "doc": "rv"}


def doc_key(s):
    """A stand-in document key rule: lower-case letters only."""
    return s.isalpha() and s.islower()


def actor(v):
    """A stand-in actor rule: a dict with a string login."""
    return isinstance(v, dict) and isinstance(v.get("login"), str)


def check(r):
    """valid_rec with the stand-in rules."""
    return valid_rec(r, doc_key, actor)


class Location(unittest.TestCase):
    """Where the pin is: file/lo/hi for a line pin, pdf/page/frac for a view-only PDF's pin - absolute paths only."""

    def test_line_and_region_pins_pass(self):
        """A complete line pin and a region pin are records the store trusts."""
        self.assertTrue(check(LINE))
        self.assertTrue(check(REGION))

    def test_line_pin_needs_an_absolute_file_and_an_ordered_integer_range(self):
        """No file, an empty or relative file, a missing, bool, zero or reversed lo/hi each make the line broken."""
        for bad in (
            {"file": None},
            {"file": ""},
            {"file": "main.tex"},
            {"lo": None},
            {"lo": True, "hi": True},
            {"lo": 0},
            {"lo": 6},
            {"hi": "5"},
        ):
            self.assertFalse(check(dict(LINE, **bad)), bad)

    def test_region_pin_needs_an_absolute_pdf_a_page_and_four_numbers(self):
        """A relative pdf, no page or page 0, lo/hi on a region pin, or a frac that is not four numbers is broken."""
        for bad in (
            {"pdf": "review.pdf"},
            {"page": None},
            {"page": 0},
            {"lo": 1, "hi": 2},
            {"frac": None},
            {"frac": [0.1, 0.2, 0.5]},
            {"frac": [0.1, 0.2, 0.5, True]},
        ):
            self.assertFalse(check(dict(REGION, **bad)), bad)

    def test_id_must_be_an_integer_and_the_record_a_dict(self):
        """Not a dict, no id, a string id or a bool id: broken."""
        self.assertFalse(check([LINE]))
        self.assertFalse(check(None))
        for bad in ({"id": None}, {"id": "3"}, {"id": True}):
            self.assertFalse(check(dict(LINE, **bad)), bad)


class Collaborators(unittest.TestCase):
    """The document key and the actor shape are the caller's rules, asked with the stored values."""

    def test_doc_is_checked_by_the_given_key_rule(self):
        """A string doc passes when the rule says so - even a document no longer configured; otherwise broken."""
        seen = []
        self.assertTrue(valid_rec(dict(LINE, doc="gone"), lambda s: seen.append(s) or True, actor))
        self.assertEqual(seen, ["gone"])
        self.assertFalse(check(dict(LINE, doc="Bad Key")))
        self.assertFalse(check(dict(LINE, doc=7)))
        self.assertTrue(check(dict(LINE, doc=None)))  # a legacy record has none

    def test_author_and_every_by_field_are_checked_by_the_given_actor_rule(self):
        """author and *_by values go to the actor rule; None is allowed; the rule's no makes the line broken."""
        for key in ("author", "closed_by", "confirmed_by", "claimed_by", "dropped_by"):
            self.assertFalse(check(dict(LINE, **{key: {"login": 1}})), key)
            self.assertTrue(check(dict(LINE, **{key: None})), key)
        asked = []
        valid_rec(dict(LINE, edited_by={"login": "b"}), doc_key, lambda v: asked.append(v) or True)
        self.assertEqual(asked, [ALICE, {"login": "b"}])


class Fields(unittest.TestCase):
    """The optional fields the viewer renders as-is must have their stored shape when present."""

    def test_optional_fields_of_the_wrong_kind_break_the_line(self):
        """Each case is one field with a shape the store has never written."""
        for bad in (
            {"page": "1"},
            {"note": 3},
            {"close_reply": 1},
            {"close_ref": []},
            {"kind_req": "Q"},
            {"mentions": "bob"},
            {"mentions": [1]},
            {"assignee": ""},
            {"assignee": 1},
            {"anchor": "x"},
            {"raw_lo": 1.5},
            {"rev": "2"},
            {"synced_at": "10:00"},
            {"claim_until": True},
            {"eta_ts": "soon"},
            {"done": 1},
            {"review": "y"},
            {"stale": "no"},
            {"name": 1},
            {"file_rel": 1},
            {"done_at": 5},
            {"at": 1},
            {"changes": [{"file": "a.tex", "lo": "1", "hi": 2}]},
            {"frac": [0, 0, 1]},
        ):
            self.assertFalse(check(dict(LINE, **bad)), bad)

    def test_known_fields_in_their_stored_shape_and_unknown_fields_pass(self):
        """A record with every optional field in its stored shape, plus a field this version does not know, passes."""
        full = dict(
            LINE,
            page=1,
            kind_req="question",
            mentions=["bob@example.com"],
            assignee="agent",
            anchor={"text": "x"},
            raw_lo=4,
            raw_hi=5,
            rev=2,
            synced_at=1790000000.5,
            score=0.9,
            claim_until=1790000100,
            claim_ts=1790000000,
            eta_ts=1790000050,
            done=False,
            review=None,
            stale=True,
            name="main.tex",
            kind="line",
            via="synctex",
            file_rel="main.tex",
            changes=[{"file": "/ms/main.tex", "lo": 1, "hi": 2}],
            done_at="2026-09-26 11:00:00",
            future_field={"anything": [1, 2]},
        )
        self.assertTrue(check(full))


class Thread(unittest.TestCase):
    """thread = [{id, by, at, text, ev?, ref?, mentions?}]: the viewer renders by.name and text as-is."""

    def entry(self, **extra):
        """One valid thread entry, with extra fields merged in."""
        return dict({"id": 1, "by": ALICE, "at": "2026-09-26 10:00:00", "text": "hi"}, **extra)

    def test_every_transition_mark_and_a_plain_reply_pass(self):
        """The marks lifecycle and edit write (close, reopen, confirm, assign) and a reply without ev are valid."""
        self.assertEqual(THREAD_EVENTS, ("close", "reopen", "confirm", "assign"))
        thread = [self.entry(id=i + 1, ev=ev) for i, ev in enumerate(THREAD_EVENTS)] + [
            self.entry(id=9, ref="PR #3", mentions=["b"])
        ]
        self.assertTrue(check(dict(LINE, thread=thread)))

    def test_a_malformed_entry_breaks_the_line(self):
        """No or a bool id, text or at not a string, by not an actor, an unknown ev, a bad ref or mentions: broken."""
        for bad in (
            {"id": None},
            {"id": True},
            {"text": None},
            {"at": 5},
            {"by": "alice"},
            {"ev": "delete"},
            {"ref": 3},
            {"mentions": "b"},
        ):
            self.assertFalse(check(dict(LINE, thread=[self.entry(**bad)])), bad)
        self.assertFalse(check(dict(LINE, thread="hi")))
        self.assertFalse(check(dict(LINE, thread=["hi"])))


class IsInt(unittest.TestCase):
    """is_int: how a JSON integer arrives - never a bool."""

    def test_ints_but_not_bools_floats_or_strings(self):
        """1 and 0 are integers; True, 1.0 and "1" are not."""
        self.assertTrue(is_int(1) and is_int(0))
        self.assertFalse(is_int(True) or is_int(1.0) or is_int("1"))


if __name__ == "__main__":
    unittest.main()

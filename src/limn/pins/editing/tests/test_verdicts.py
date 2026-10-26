"""Verdict pins through pin creation and editing (docs/superpowers/specs/2026-10-26-verdict-pins.md §HTTP API,
§보안과 기록, D3).

First the pure decision on a new pin's verdict (decide_new_verdict: who may make one, the document's words, the word
asked for, a question or a suggestion beside it - in that order) and the record it writes, then POST /api/pin over a
real server and state folder: what is stored and answered, that every refusal writes nothing and allocates no pin
number, that the words are read at the moment of the request, and the authorization matrix of the roles. Then the
edit rule: a verdict pin's edit changes its note-level fields only (decide_edit, verdict_fixed), checked on the pin
as the edit would leave it, and line matching still moves a verdict pin.

Run: uv run pytest -q src/limn/pins/editing/tests/test_verdicts.py
"""

import json
import unittest

from limn.documents.verdicts import verdicts_path
from limn.pins.editing.fields import parse_verdict
from limn.pins.editing.input import parse_edit
from limn.pins.editing.rules import (
    AddRequest,
    Anchoring,
    ClosedPinReshaped,
    EditRequest,
    LinePlace,
    NonStringVerdict,
    PinEdited,
    RegionPlace,
    RemoveSuggestion,
    VerdictByAgent,
    VerdictConflict,
    VerdictFacts,
    VerdictFixed,
    VerdictUnknown,
    VerdictUnsupported,
    decide_edit,
    decide_new_verdict,
    new_line_pin,
    new_region_pin,
)
from limn.pins.model import DonePin, OpenPin
from limn.pins.suggestion import Suggestion
from limn.web.errors import InputRejected

from helpers import ps, set_config
from helpers_access import ALICE, BOB, CAROL, DAVE, AccessBase, token_create
from helpers_pin_rules import ALICE_PERSON, AT

WORDS = {
    "format": "limn-verdicts/1",
    "page": True,
    "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}],
}
KEYS = ("채택", "보류", "삭제")
LINE = LinePlace(
    {"file": "/ms/main.tex", "name": "main.tex", "lo": 4, "hi": 5, "page": 1}, frozenset({"file", "lo", "hi", "page"})
)
REGION = RegionPlace({"pdf": "/ms/r.pdf", "name": "r.pdf", "kind": "region", "page": 1, "frac": [0, 0, 1, 1]})
HUMAN = VerdictFacts(True, KEYS)


class ParseVerdict(unittest.TestCase):
    """The body's verdict is taken as sent: nothing is refused while parsing."""

    def test_a_string_is_kept_null_is_absent_and_anything_else_is_not_a_string(self):
        """A string (any string) is the verdict asked for; null or absence is no verdict; any other JSON value is
        NonStringVerdict, refused later as verdict_unknown."""
        self.assertEqual(parse_verdict("채택"), "채택")
        self.assertEqual(parse_verdict("a|b"), "a|b")
        self.assertIsNone(parse_verdict(None))
        for v in (1, True, ["채택"], {"key": "채택"}):
            with self.subTest(v=v):
                self.assertEqual(parse_verdict(v), NonStringVerdict())


class DecideNewVerdict(unittest.TestCase):
    """decide_new_verdict's answers and their order."""

    def test_a_person_picking_a_declared_word_gets_that_key(self):
        """An editor or owner asking for one of the document's keys gets exactly that key to store."""
        for key in KEYS:
            with self.subTest(key=key):
                self.assertEqual(decide_new_verdict(key, AddRequest(LINE, ""), HUMAN), key)

    def test_each_refusal_in_turn(self):
        """An agent; a document without words; a word it does not declare, or a non-string; a question or a
        suggestion beside the verdict."""
        self.assertEqual(decide_new_verdict("채택", AddRequest(LINE, ""), VerdictFacts(False, KEYS)), VerdictByAgent())
        self.assertEqual(decide_new_verdict("채택", AddRequest(LINE, ""), VerdictFacts(True, ())), VerdictUnsupported())
        self.assertEqual(decide_new_verdict("채텍", AddRequest(LINE, ""), HUMAN), VerdictUnknown(KEYS))
        self.assertEqual(decide_new_verdict(NonStringVerdict(), AddRequest(LINE, ""), HUMAN), VerdictUnknown(KEYS))
        self.assertEqual(
            decide_new_verdict("채택", AddRequest(LINE, "", kind_req="question"), HUMAN), VerdictConflict()
        )
        self.assertEqual(
            decide_new_verdict("채택", AddRequest(LINE, "", suggest=Suggestion("a", "b")), HUMAN), VerdictConflict()
        )
        self.assertEqual(decide_new_verdict("채택", AddRequest(LINE, "", kind_req="fix"), HUMAN), "채택")

    def test_an_earlier_check_wins_over_a_later_one(self):
        """A request that breaks several rules gets the first one's refusal: author, then words, then the word, then
        the conflict."""
        question = AddRequest(LINE, "", kind_req="question", suggest=Suggestion("a", "b"))
        self.assertEqual(decide_new_verdict("x", question, VerdictFacts(False, ())), VerdictByAgent())
        self.assertEqual(decide_new_verdict("x", question, VerdictFacts(True, ())), VerdictUnsupported())
        self.assertEqual(decide_new_verdict("x", question, HUMAN), VerdictUnknown(KEYS))
        self.assertEqual(decide_new_verdict("채택", question, HUMAN), VerdictConflict())

    def test_a_request_with_a_suggestion_is_always_refused(self):
        """Whatever the facts, a verdict asked for beside a suggestion never gets a key to store, so the suggestion
        is never written on a verdict pin."""
        request = AddRequest(LINE, "", suggest=Suggestion("a", "b"))
        for author in (False, True):
            for keys in ((), KEYS):
                for asked in ("채택", "x", NonStringVerdict()):
                    with self.subTest(author=author, keys=keys, asked=asked):
                        self.assertNotIsInstance(decide_new_verdict(asked, request, VerdictFacts(author, keys)), str)


class NewRecord(unittest.TestCase):
    """The verdict is the last field of a new pin's record, line or region."""

    def test_the_verdict_is_written_last_and_only_when_given(self):
        """A line pin and a region pin end with their verdict; without one there is no verdict field."""
        anchoring = Anchoring({"head": "h", "tail": "t"}, 1.0)
        author = {"login": "alice@example.com", "name": "Alice Kim"}
        line = new_line_pin(LINE, AddRequest(LINE, ""), 1, AT, author, (), anchoring, "b1", "main", None, "채택")
        region = new_region_pin(REGION, AddRequest(REGION, ""), 2, AT, author, (), "b1", "rv", "보류")
        self.assertEqual(list(line.record)[-1], "verdict")
        self.assertEqual(line.record["verdict"], "채택")
        self.assertEqual(list(region.record)[-1], "verdict")
        self.assertEqual(region.record["verdict"], "보류")
        plain = new_line_pin(LINE, AddRequest(LINE, ""), 3, AT, author, (), anchoring, "b1", "main", None)
        self.assertNotIn("verdict", plain.record)


class VerdictHttpBase(AccessBase):
    """AccessBase with people.json naming owner Alice, editor Bob, viewer Carol and agent-role Dave, an API token, and
    the example word file next to main.tex."""

    def setUp(self):
        """The people, the token and the word file."""
        super().setUp()
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
                {"login": "bob@example.com", "name": "Bob Park", "role": "editor"},
                {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"},
                {"login": "dave@example.com", "name": "Dave Choi", "role": "agent"},
            ]
        )
        _, self.token = token_create(ps.APP.C.state, "ci")
        self.words = verdicts_path(ps.APP.docs[0])
        self.words.write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")

    def body(self, **extra):
        """A new pin on main.tex lines 4-5 with the given extra fields."""
        return {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "", **extra}

    def stored_bytes(self):
        """pins.jsonl and pins.seq as they are on disk now (b'' when missing)."""
        files = (ps.APP.C.pins_jsonl, ps.APP.C.state / "pins.seq")
        return tuple(f.read_bytes() if f.exists() else b"" for f in files)

    def refused(self, want_code, want_body, body, **who):
        """POST /api/pin answers want_code with exactly want_body and writes nothing."""
        before = self.stored_bytes()
        code, d = self.call("POST", "/api/pin", body, **who)
        self.assertEqual((code, d), (want_code, want_body))
        self.assertEqual(self.stored_bytes(), before)


HUMAN_ONLY = {"error": "판정은 사람이 정합니다 — 에이전트는 판정 핀을 만들지 않습니다.", "reason": "verdict_human"}
UNSUPPORTED = {"error": "이 문서에는 판정 낱말이 없습니다.", "reason": "verdict_unsupported"}
UNKNOWN = {"error": "이 문서의 판정 낱말이 아닙니다.", "reason": "verdict_unknown", "choices": list(KEYS)}
CONFLICT = {"error": "판정 핀은 질문·제안 수정과 함께 쓰지 않습니다.", "reason": "verdict_conflict"}


class CreateOverHttp(VerdictHttpBase):
    """POST /api/pin with a verdict, by people allowed to make one."""

    def test_a_person_makes_a_verdict_pin_and_every_read_shows_it_as_stored(self):
        """Bob's verdict pin is stored with the key last; GET /api/pins and /api/pins/N carry it as stored, with no
        computed field."""
        code, d = self.call("POST", "/api/pin", self.body(verdict="채택"), headers=BOB)
        self.assertEqual(code, 200, d)
        stored = self.pin(d["id"])
        self.assertEqual(list(stored)[-1], "verdict")
        self.assertEqual(stored["verdict"], "채택")
        _, listed = self.call("GET", "/api/pins", headers=BOB)
        _, one = self.call("GET", "/api/pins/%d" % d["id"], headers=BOB)
        for shown in (next(p for p in listed if p["id"] == d["id"]), one["pin"]):
            self.assertEqual(shown["verdict"], "채택")
            self.assertEqual({k for k in shown if "verdict" in k}, {"verdict"})

    def test_a_null_verdict_is_an_ordinary_pin(self):
        """verdict: null asks for nothing - an ordinary pin, even for an agent and without a word file."""
        self.words.unlink()
        code, d = self.call("POST", "/api/pin", self.body(verdict=None, note="n"), token=self.token)
        self.assertEqual(code, 200, d)
        self.assertNotIn("verdict", self.pin(d["id"]))

    def test_the_words_are_those_of_the_moment(self):
        """A word added to the file is accepted at once and one removed is refused at once - no restart."""
        self.refused(400, dict(UNKNOWN, choices=list(KEYS)), self.body(verdict="재검토"), headers=BOB)
        words = dict(WORDS, verdicts=[*WORDS["verdicts"], {"key": "재검토"}])
        self.words.write_text(json.dumps(words, ensure_ascii=False) + " ", encoding="utf-8")
        code, d = self.call("POST", "/api/pin", self.body(verdict="재검토"), headers=BOB)
        self.assertEqual(code, 200, d)
        self.words.write_text(json.dumps(dict(WORDS, verdicts=[{"key": "보류"}]), ensure_ascii=False), encoding="utf-8")
        self.refused(400, dict(UNKNOWN, choices=["보류"]), self.body(verdict="채택"), headers=BOB)

    def test_a_document_without_usable_words_refuses_a_verdict(self):
        """No word file, or one that cannot be used, is verdict_unsupported."""
        self.words.write_text("{", encoding="utf-8")
        self.refused(400, UNSUPPORTED, self.body(verdict="채택"), headers=BOB)
        self.words.unlink()
        self.refused(400, UNSUPPORTED, self.body(verdict="채택"), headers=BOB)

    def test_a_word_the_document_does_not_declare_is_refused_with_its_choices(self):
        """A misspelt word, a label instead of a key, or a non-string is verdict_unknown with the keys in file order."""
        for verdict in ("채텍", "", 3, ["채택"]):
            with self.subTest(verdict=verdict):
                self.refused(400, UNKNOWN, self.body(verdict=verdict), headers=BOB)

    def test_a_question_or_a_suggestion_beside_a_verdict_is_a_conflict(self):
        """kind_req question and any suggest - even one whose base is not the file - are verdict_conflict."""
        self.refused(400, CONFLICT, self.body(verdict="채택", kind_req="question"), headers=BOB)
        for suggest in ({"base": "not these lines", "text": "x"}, {"base": "x", "text": "x"}):
            with self.subTest(suggest=suggest):
                self.refused(400, CONFLICT, self.body(verdict="채택", suggest=suggest), headers=BOB)

    def test_the_refusals_come_in_their_order(self):
        """An agent with an unknown word on a document without words is told verdict_human; a person with an unknown
        word and a question is told verdict_unknown."""
        self.words.unlink()
        self.refused(403, HUMAN_ONLY, self.body(verdict="x", kind_req="question"), token=self.token)
        self.refused(400, UNSUPPORTED, self.body(verdict="x", kind_req="question"), headers=BOB)
        self.words.write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")
        self.refused(400, UNKNOWN, self.body(verdict="x", kind_req="question"), headers=BOB)

    def test_a_refused_verdict_allocates_no_pin_number(self):
        """After a refusal the next pin gets the number it would have got without it."""
        code, first = self.call("POST", "/api/pin", self.body(verdict="채택"), headers=BOB)
        self.assertEqual(code, 200, first)
        self.refused(400, UNKNOWN, self.body(verdict="x"), headers=BOB)
        code, second = self.call("POST", "/api/pin", self.body(verdict="보류"), headers=BOB)
        self.assertEqual(second["id"], first["id"] + 1)


class AuthorMatrix(VerdictHttpBase):
    """Who may make a verdict pin, end to end: editor and owner people only. Every refusal writes nothing."""

    def test_owner_and_editor_people_make_verdict_pins(self):
        """Alice (owner) and Bob (editor) both get 200 and a stored verdict."""
        for headers in (ALICE, BOB):
            with self.subTest(who=headers["Tailscale-User-Login"]):
                code, d = self.call("POST", "/api/pin", self.body(verdict="보류"), headers=headers)
                self.assertEqual(code, 200, d)
                self.assertEqual(self.pin(d["id"])["verdict"], "보류")

    def test_the_local_owner_makes_verdict_pins(self):
        """--auth local: the loopback owner is a person, so a verdict pin is made."""
        set_config(auth="local", agent_loopback=False)
        code, d = self.call("POST", "/api/pin", self.body(verdict="채택"))
        self.assertEqual(code, 200, d)

    def test_agents_are_refused_whatever_their_identity(self):
        """A token, the headerless loopback agent and a person whose role is agent are all 403 verdict_human."""
        for who in (dict(token=self.token), {}, dict(headers=DAVE)):
            with self.subTest(who=who):
                self.refused(403, HUMAN_ONLY, self.body(verdict="채택"), **who)

    def test_a_viewer_is_refused_by_its_role_first(self):
        """A viewer gets the role refusal every pin gets (403 viewer_only), not the verdict refusal."""
        self.refused(
            403,
            {
                "error": "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.",
                "reason": "viewer_only",
            },
            self.body(verdict="채택"),
            headers=CAROL,
        )

    def test_agents_still_make_ordinary_pins(self):
        """The refusal is about the verdict: the same agents may still make a pin without one."""
        for who in (dict(token=self.token), {}, dict(headers=DAVE)):
            with self.subTest(who=who):
                code, d = self.call("POST", "/api/pin", self.body(note="n"), **who)
                self.assertEqual(code, 200, d)


def verdict_pin(**extra):
    """An open verdict pin (채택) on main.tex lines 4-5 at rev 2, with whatever extra stored fields are given."""
    record = {"id": 3, "file": "/ms/main.tex", "lo": 4, "hi": 5, "note": "", "rev": 2, "verdict": "채택", **extra}
    return OpenPin.from_record(record)


def decide(pin, request):
    """decide_edit by Alice at AT with clock 10:00, the pin's file holding 20 lines and the note limit of 4000."""
    return decide_edit(pin, request, ALICE_PERSON, AT, "10:00", 20, 4000, None)


# Each edit field a verdict pin may not take (D3), as a request that sends only it.
TARGET_FIELDS = {
    "verdict": EditRequest(base_rev=2, verdict_sent=True),
    "loc": EditRequest(
        base_rev=2,
        place=LinePlace(
            {"file": "/ms/main.tex", "name": "main.tex", "lo": 8, "hi": 9, "page": 1}, frozenset({"file", "lo", "hi"})
        ),
    ),
    "lo": EditRequest(base_rev=2, lo=3),
    "hi": EditRequest(base_rev=2, hi=6),
    "scope": EditRequest(base_rev=2, scope="para"),
    "kind": EditRequest(base_rev=2, kind="lines"),
    "kind_req": EditRequest(base_rev=2, kind_req="fix"),
    "suggest": EditRequest(base_rev=2, suggest=Suggestion("a", "b")),
    "suggest null": EditRequest(base_rev=2, suggest=RemoveSuggestion()),
}
# The note-level fields a verdict pin's edit may change.
NOTE_FIELDS = {
    "note": EditRequest(base_rev=2, note="이 그림만"),
    "note_append": EditRequest(note_append="덧붙임"),
    "assignee": EditRequest(base_rev=2, assignee="agent"),
    "mention hints": EditRequest(base_rev=2, note="@bob", hints=("bob@example.com",)),
}


class EditRule(unittest.TestCase):
    """decide_edit on a verdict pin, and on a pin an edit would give a verdict."""

    def test_every_field_that_fixes_a_verdict_pin_is_refused(self):
        """The verdict, a re-placement, lo, hi, scope, kind, kind_req and a suggestion set or removed are each
        VerdictFixed on its own - even kind_req fix, which the pin already is."""
        for name, request in TARGET_FIELDS.items():
            with self.subTest(field=name):
                self.assertEqual(decide(verdict_pin(), request), VerdictFixed())

    def test_note_level_fields_are_edited_as_on_any_pin(self):
        """The note, an appended note, the assignee and @-tag hints change a verdict pin as they change any pin."""
        for name, request in NOTE_FIELDS.items():
            with self.subTest(field=name):
                self.assertIsInstance(decide(verdict_pin(), request), PinEdited)

    def test_sending_a_verdict_to_a_pin_without_one_is_refused(self):
        """The pin the edit would leave is a verdict pin, so the verdict it sends is refused like any change of one."""
        plain = OpenPin.from_record({"id": 3, "file": "/ms/main.tex", "lo": 4, "hi": 5, "note": "n", "rev": 2})
        self.assertEqual(decide(plain, EditRequest(base_rev=2, verdict_sent=True)), VerdictFixed())
        self.assertIsInstance(decide(plain, TARGET_FIELDS["loc"]), PinEdited)

    def test_a_stored_value_that_is_no_verdict_leaves_an_ordinary_pin(self):
        """A stored verdict that is not a key-shaped string is not promoted: the pin is edited like any other."""
        for stored in (7, "", "a|b", "x" * 17, None, ["채택"]):
            with self.subTest(stored=stored):
                self.assertIsInstance(decide(verdict_pin(verdict=stored), TARGET_FIELDS["loc"]), PinEdited)

    def test_the_rule_comes_before_the_closed_and_stale_checks(self):
        """A closed verdict pin's re-placement and a stale one are VerdictFixed; its note still changes."""
        done = DonePin.from_record({**verdict_pin().record, "done": True})
        self.assertEqual(decide(done, TARGET_FIELDS["loc"]), VerdictFixed())
        self.assertIsInstance(decide(done, NOTE_FIELDS["note"]), PinEdited)
        plain_done = DonePin.from_record({"id": 3, "file": "/ms/main.tex", "lo": 4, "hi": 5, "rev": 2, "done": True})
        self.assertIsInstance(decide(plain_done, TARGET_FIELDS["loc"]), ClosedPinReshaped)
        self.assertEqual(decide(verdict_pin(), EditRequest(base_rev=9, lo=3)), VerdictFixed())


class EditBody(unittest.TestCase):
    """parse_edit records a sent verdict, with any value, as something the edit asks to change."""

    def test_a_verdict_key_counts_as_a_change_whatever_its_value(self):
        """{verdict, base_rev} is not nothing_to_change; null counts too. Without the key the flag is off."""
        for value in ("채택", None, 3):
            with self.subTest(value=value):
                body = parse_edit({"verdict": value, "base_rev": 0}, ())
                self.assertNotIsInstance(body, InputRejected)
                self.assertTrue(body.request.verdict_sent)
        self.assertFalse(parse_edit({"note": "n", "base_rev": 0}, ()).request.verdict_sent)


FIXED = {
    "error": "판정 핀은 판정과 대상을 바꾸지 않습니다 — 새 판정 핀을 찍거나 이 핀을 지웁니다.",
    "reason": "verdict_fixed",
}


class EditOverHttp(VerdictHttpBase):
    """POST /api/pins/{id}/edit on verdict pins through the handler; a refusal writes nothing."""

    def setUp(self):
        """A verdict pin by Bob on main.tex lines 4-5."""
        super().setUp()
        code, d = self.call("POST", "/api/pin", self.body(verdict="보류"), headers=BOB)
        self.assertEqual(code, 200, d)
        self.pid = d["id"]

    def edit(self, body, **who):
        """POST the edit of the verdict pin with the pin's current rev."""
        return self.call("POST", "/api/pins/%d/edit" % self.pid, {**body, "base_rev": self.pin(self.pid)["rev"]}, **who)

    def test_a_person_and_an_agent_edit_the_note(self):
        """Bob replaces the note, an agent appends to it; the verdict stays."""
        code, d = self.edit({"note": "이 그림만"}, headers=BOB)
        self.assertEqual(code, 200, d)
        code, d = self.edit({"note_append": "확인함"}, token=self.token)
        self.assertEqual(code, 200, d)
        self.assertEqual(self.pin(self.pid)["verdict"], "보류")
        self.assertIn("확인함", self.pin(self.pid)["note"])

    def test_moving_or_retyping_a_verdict_pin_is_refused_for_everyone(self):
        """A re-placement, a range, kind_req or a new verdict is 400 verdict_fixed for a person and an agent alike."""
        loc = {"file": str(self.main), "lo": 8, "hi": 9, "page": 1}
        for body in ({"loc": loc}, {"lo": 8, "hi": 9}, {"kind_req": "question"}, {"verdict": "채택"}):
            for who in (dict(headers=BOB), dict(token=self.token)):
                with self.subTest(body=body, who=who):
                    before = self.stored_bytes()
                    self.assertEqual(self.edit(body, **who), (400, FIXED))
                    self.assertEqual(self.stored_bytes(), before)

    def test_a_verdict_sent_to_an_ordinary_pin_is_refused(self):
        """An edit cannot turn a pin into a verdict pin."""
        code, d = self.call("POST", "/api/pin", self.body(note="n"), headers=BOB)
        before = self.stored_bytes()
        got = self.call("POST", "/api/pins/%d/edit" % d["id"], {"verdict": "채택", "base_rev": 0}, headers=BOB)
        self.assertEqual(got, (400, FIXED))
        self.assertEqual(self.stored_bytes(), before)

    def test_line_matching_moves_a_verdict_pin(self):
        """Lines inserted above a verdict pin move it as they move any pin: re-sync is not an edit."""
        text = self.main.read_text(encoding="utf-8")
        self.main.write_text("% one\n% two\n" + text, encoding="utf-8")
        moved = self.pin(self.pid)
        self.assertEqual((moved["lo"], moved["hi"]), (6, 7))
        self.assertEqual(moved["verdict"], "보류")

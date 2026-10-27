"""Verdict pins through pin creation and editing (docs/superpowers/specs/2026-10-26-verdict-pins.md §HTTP API,
§보안과 기록, D3).

First the pure decision on a new pin's verdict (decide_new_verdict: who may make one, the document's words, the word
asked for, a question or a suggestion beside it - in that order) and the record it writes, then POST /api/pin over a
real server and state folder: what is stored and answered, that every refusal writes nothing and allocates no pin
number, that the words are read at the moment of the request, the authorization matrix of the roles, and the root
check of a whole-figure verdict against its build's map (verdict_page_target) - the build the pin stores, even when
another is published meanwhile (over a real store, with a build owner that changes its answer), and that a
verdict's reads - the word file and the root check - are made before the pin lock, so one that stalls holds up no
other pin operation. Then the edit rule: a verdict pin's edit changes its note-level fields only (decide_edit,
verdict_fixed), checked on the pin as the edit would leave it, and line matching still moves a verdict pin.

Run: uv run pytest -q src/limn/pins/editing/tests/test_verdicts.py
"""

import json
import threading
import unittest
from dataclasses import dataclass, replace

from limn.documents.verdicts import verdicts_path
from limn.pins.editing import service as add_edit
from limn.pins.editing.fields import parse_verdict
from limn.pins.editing.input import parse_edit, parse_edit_place
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
    StaleEdit,
    UnreadLoc,
    VerdictByAgent,
    VerdictConflict,
    VerdictFacts,
    VerdictFixed,
    VerdictPageTarget,
    VerdictUnknown,
    VerdictUnsupported,
    decide_edit,
    decide_new_verdict,
    new_line_pin,
    new_region_pin,
)
from limn.pins.model import DonePin, OpenPin
from limn.pins.suggestion import Suggestion
from limn.runtime.documents import Doc
from limn.web.errors import InputRejected

from helpers import MINI_PDF, ps, set_config
from helpers_access import ALICE, ALICE_ACTOR, BOB, BOB_ACTOR, CAROL, DAVE, AccessBase, token_create
from helpers_authority import post_authority
from helpers_figure import BUILD1, BUILD2, SCRIPT, figure_doc, viewer_map, write_build
from helpers_pin_rules import ALICE_PERSON, AT
from helpers_pin_service import ServiceBase

# The word file the HTTP tests write: 채택's button reads 본문으로, a label - what a pin stores is always the key.
WORDS = {
    "format": "limn-verdicts/1",
    "page": True,
    "verdicts": [{"key": "채택", "label": "본문으로"}, {"key": "보류"}, {"key": "삭제", "confirm": True}],
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

    def test_an_unconfirmed_whole_figure_is_refused_last(self):
        """A whole figure the map does not confirm is VerdictPageTarget - after every other check."""
        unconfirmed = VerdictFacts(True, KEYS, page_target_holds=False)
        self.assertEqual(decide_new_verdict("채택", AddRequest(LINE, ""), unconfirmed), VerdictPageTarget())
        self.assertEqual(decide_new_verdict("x", AddRequest(LINE, ""), unconfirmed), VerdictUnknown(KEYS))
        self.assertEqual(
            decide_new_verdict("채택", AddRequest(LINE, "", kind_req="question"), unconfirmed), VerdictConflict()
        )

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
PAGE_TARGET = {
    "error": "그 쪽의 그림을 확인하지 못했습니다 — 그림 위를 끌어 고른 뒤 판정합니다.",
    "reason": "verdict_page_target",
}


class CreateOverHttp(VerdictHttpBase):
    """POST /api/pin with a verdict, by people allowed to make one."""

    def test_a_person_makes_a_verdict_pin_and_every_read_shows_it_as_stored(self):
        """Bob's verdict pin is stored with the key last - 채택, not its label 본문으로; GET /api/pins and /api/pins/N
        carry it as stored, with no computed field."""
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
        """A misspelt word, a label instead of a key (본문으로, the button name of 채택), or a non-string is
        verdict_unknown with the keys - never a label - in file order, and nothing is written."""
        for verdict in ("채텍", "본문으로", "", 3, ["채택"]):
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


class RootCheck(VerdictHttpBase):
    """A figure document's verdict pin that names its page's whole figure (el.path == [el.id]) is checked against the
    map of its build (pdf_build, else the build on screen): the figure must be that page's root."""

    def setUp(self):
        """LaTeX document ms and figure document fig, fig with the word file; build BUILD2 (no map) and then BUILD1
        (the two-page viewer_map(): figure B2 on page 1, B3 on page 2) on screen."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD2, None)
        write_build(self.fig, BUILD1, viewer_map(), pages=2)
        verdicts_path(self.fig).write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")

    def line(self, el, page=1, **extra):
        """A verdict pin body on the drawing script's lines 12-140 at the figure rung, naming el."""
        body = {"doc": "fig", "file": SCRIPT, "lo": 12, "hi": 140, "page": page, "scope": "fig", "el": el}
        return {"verdict": "채택", "note": "", "pdf_build": BUILD1, **body, **extra}

    def region(self, el, page=1, **extra):
        """A verdict region pin body over the whole page, naming el."""
        return {
            "doc": "fig",
            "page": page,
            "frac": [0, 0, 1, 1],
            "el": el,
            "verdict": "채택",
            "pdf_build": BUILD1,
            **extra,
        }

    def test_the_figure_of_the_page_is_confirmed(self):
        """B2 on page 1 and B3 on page 2 of BUILD1 are their pages' roots: stored, as a line pin and as a region pin,
        with or without pdf_build (the build on screen is BUILD1)."""
        bodies = (
            self.line({"id": "B2", "path": ["B2"]}),
            self.line({"id": "B2", "path": ["B2"]}, pdf_build=None),
            self.region({"id": "B3", "path": ["B3"]}, page=2),
        )
        for body in bodies:
            with self.subTest(body=body):
                code, d = self.call("POST", "/api/pin", body, headers=BOB)
                self.assertEqual(code, 200, d)
                self.assertEqual(self.pin(d["id"])["verdict"], "채택")

    def test_an_element_that_is_not_the_root_of_that_page_is_refused(self):
        """A panel claiming to be a whole figure, the figure of another page, and a figure on a build without a map are
        verdict_page_target, and nothing is written."""
        for body in (
            self.line({"id": "B2/calendar", "path": ["B2/calendar"]}),
            self.line({"id": "B3", "path": ["B3"]}),
            self.region({"id": "B2", "path": ["B2"]}, page=2),
            self.line({"id": "B2", "path": ["B2"]}, pdf_build=BUILD2),
        ):
            with self.subTest(body=body):
                self.refused(400, PAGE_TARGET, body, headers=BOB)

    def test_only_a_verdict_on_a_whole_figure_is_checked(self):
        """A verdict on a panel (its path holds its ancestors) is not a page target; a pin without a verdict is never
        checked - both are stored as before."""
        panel = {"id": "B2/calendar", "path": ["B2", "B2/calendar"]}
        not_root = {"id": "B3", "path": ["B3"]}
        for body in (self.line(panel), self.line(not_root, verdict=None)):
            with self.subTest(body=body):
                code, d = self.call("POST", "/api/pin", body, headers=BOB)
                self.assertEqual(code, 200, d)

    def test_the_root_check_comes_after_every_other_refusal(self):
        """An agent, an unknown word and a question are told so before an unconfirmed figure is."""
        not_root = {"id": "B3", "path": ["B3"]}
        self.refused(403, HUMAN_ONLY, self.line(not_root), token=self.token)
        self.refused(400, UNKNOWN, self.line(not_root, verdict="x"), headers=BOB)
        self.refused(400, CONFLICT, self.line(not_root, kind_req="question"), headers=BOB)


@dataclass(frozen=True)
class OnScreen:
    """The build a fake build owner shows on screen (limn.pins.needs.HeadingStamps): its name, no stamps."""

    build: str
    head: str | None = None
    built_at: str | None = None


class RootCheckedOnTheStoredBuild(ServiceBase):
    """add_pin for a whole-figure verdict pin that sends no pdf_build checks the root on the build it stores, even
    when the build owner publishes another build while the pin is being made."""

    def test_a_build_published_meanwhile_is_not_stored_unchecked(self):
        """The build owner shows BUILD1, whose map has B2 as page 1's root, at its first answer and BUILD2, which has
        no map, at every later one. The pin is made, and the pdf_build it stores is a build its figure was confirmed
        on - never BUILD2."""
        shown = iter([BUILD1])
        confirmed: list[str] = []

        def heading(doc):
            """BUILD1 the first time it is asked, BUILD2 from then on."""
            return OnScreen(next(shown, BUILD2))

        def page_root(doc, build, page, element):
            """Only BUILD1's map has B2 as page 1's root; every build confirmed is recorded."""
            holds = (build, page, element) == (BUILD1, 1, "B2")
            if holds:
                confirmed.append(build)
            return holds

        builds = replace(self.ctx.builds, heading=heading, page_root=page_root)
        self.ctx = self.context(builds=builds, verdict_keys=lambda doc: KEYS)
        fig = Doc("fig", "그림", "figure", self.ms, self.ms / "figures.limnmap.json", paths=self.doc.paths)
        place = RegionPlace(
            {
                "pdf": str(self.ms / "figures.pdf"),
                "name": "figures.pdf",
                "kind": "region",
                "page": 1,
                "frac": [0, 0, 1, 1],
                "el": {"id": "B2", "path": ["B2"]},
            }
        )
        made = add_edit.add_pin(
            self.ctx, fig, AddRequest(place, "", verdict="채택"), post_authority(self.ctx.store, BOB_ACTOR, "add", fig)
        )
        self.assertIsInstance(made, OpenPin)
        stored = self.pin(made.core.id)
        self.assertEqual(stored["verdict"], "채택")
        self.assertIn(stored["pdf_build"], confirmed)


# How long a pin operation that should not wait for the pin lock may take, and how long a stalled read waits before it
# gives up - bounds that keep a regression from hanging the suite.
PROMPT = 5.0
STALL = 30.0


class ReadsOutsideThePinLock(ServiceBase):
    """add_pin reads a verdict's facts - the document's word file (ctx.verdict_keys) and a whole figure's root on its
    build's map (ctx.builds.page_root) - before taking the pin lock. While one of those reads stalls for document A's
    new verdict pin, a pin operation on document B and another one on A run to the end, and the stalled creation is
    then decided against what it read."""

    def setUp(self):
        """Documents A (self.doc, main.tex) and B (other.tex in the same manuscript folder), an ordinary pin on A to
        edit, and the events a stalled read waits on and announces."""
        super().setUp()
        (self.ms / "other.tex").write_text("uno\ndos\n", encoding="utf-8")
        self.other = Doc("other", "Other", "tex", self.ms, self.ms / "other.tex", paths=self.doc.paths)
        self.on_a = self.add()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.addCleanup(self.release.set)  # a failing run must not leave the stalled read waiting

    def stall(self, answer):
        """Announce that the read has started, wait until the test releases it (at most STALL seconds), then answer."""
        self.entered.set()
        self.release.wait(STALL)
        return answer

    def line(self, doc, file, **extra):
        """A new line pin request on lines 1-2 of file in doc."""
        place = LinePlace(
            {"file": str(file), "name": file.name, "lo": 1, "hi": 2, "page": 1}, frozenset({"file", "lo", "hi", "page"})
        )
        return AddRequest(place, "", **extra)

    def start(self, call):
        """Run call() on a daemon thread; the thread and the list its answer (or exception) lands in."""
        out = []

        def run():
            """Keep call's answer, or the exception it raised, for the test thread."""
            try:
                out.append(call())
            except BaseException as error:  # noqa: BLE001 - handed back to the test thread
                out.append(error)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, out

    def finishes(self, call):
        """call()'s answer, which must come within PROMPT seconds - it does not wait for the pin lock."""
        thread, out = self.start(call)
        thread.join(PROMPT)
        self.assertFalse(thread.is_alive(), "the pin operation waited for the pin lock behind a stalled read")
        self.assertNotIsInstance(out[0], BaseException)
        return out[0]

    def others_finish_while_stalled(self, D, request):
        """Start D's new verdict pin from request; once its read stalls, add a pin on B and edit A's pin, each to the
        end, with the creation still waiting; then release the read -> the creation's answer."""
        creating, made = self.start(
            lambda: add_edit.add_pin(self.ctx, D, request, post_authority(self.ctx.store, BOB_ACTOR, "add", D))
        )
        self.addCleanup(creating.join, STALL)
        self.addCleanup(self.release.set)  # runs first: a failing run releases the read, then joins
        self.assertTrue(self.entered.wait(PROMPT), "the verdict read did not start")
        added = self.finishes(
            lambda: add_edit.add_pin(
                self.ctx,
                self.other,
                self.line(self.other, self.other.main),
                post_authority(self.ctx.store, ALICE_ACTOR, "add", self.other),
            )
        )
        edited = self.finishes(
            lambda: add_edit.edit_pin(
                self.ctx,
                self.on_a,
                EditRequest(base_rev=0, note="m"),
                post_authority(self.ctx.store, ALICE_ACTOR, "edit", self.on_a),
            )
        )
        self.assertIsInstance(added, OpenPin)
        self.assertIsInstance(edited, OpenPin)
        self.assertEqual(self.pin(self.on_a)["note"], "m")
        self.assertTrue(creating.is_alive())
        self.release.set()
        creating.join(PROMPT)
        self.assertFalse(creating.is_alive())
        return made[0]

    def test_a_stalled_word_file_holds_up_no_other_pin_operation(self):
        """A's word file read stalls: B's new pin and the edit of A's pin are made meanwhile, and A's verdict pin is
        then stored with the word it read, numbered after them."""
        self.ctx = self.context(verdict_keys=lambda doc: self.stall(KEYS) if doc.key == self.doc.key else ())
        made = self.others_finish_while_stalled(self.doc, self.line(self.doc, self.tex, verdict="채택"))
        self.assertIsInstance(made, OpenPin)
        self.assertEqual(self.pin(made.core.id)["verdict"], "채택")
        self.assertEqual(made.core.id, self.on_a + 2)

    def test_a_stalled_word_file_still_refuses_in_order(self):
        """A stalled read that ends with no words, or with words lacking the one asked for, is refused as before -
        verdict_unsupported, then verdict_unknown with the keys - and writes nothing."""
        for keys, want in (((), VerdictUnsupported()), (KEYS, VerdictUnknown(KEYS))):
            with self.subTest(keys=keys):
                self.entered.clear()
                self.release.clear()
                self.ctx = self.context(verdict_keys=lambda doc, keys=keys: self.stall(keys))
                creating, made = self.start(
                    lambda: add_edit.add_pin(
                        self.ctx,
                        self.doc,
                        self.line(self.doc, self.tex, verdict="재검토"),
                        post_authority(self.ctx.store, BOB_ACTOR, "add", self.doc),
                    )
                )
                self.assertTrue(self.entered.wait(PROMPT))
                before = self.pins_bytes()
                self.release.set()
                creating.join(PROMPT)
                self.assertEqual(made, [want])
                self.assertEqual(self.pins_bytes(), before)

    def test_a_stalled_root_check_holds_up_no_other_pin_operation(self):
        """A figure document's whole-figure verdict pin without pdf_build: the root check on its build's map stalls,
        B's new pin and the edit of A's pin are made meanwhile, and the verdict pin is then stored on the build its
        figure was checked on."""
        fig = Doc("fig", "그림", "figure", self.ms, self.ms / "figures.limnmap.json", paths=self.doc.paths)
        builds = replace(
            self.ctx.builds,
            heading=lambda doc: OnScreen(BUILD1),
            page_root=lambda doc, build, page, element: self.stall((build, page, element) == (BUILD1, 1, "B2")),
        )
        self.ctx = self.context(builds=builds, verdict_keys=lambda doc: KEYS)
        place = RegionPlace(
            {
                "pdf": str(self.ms / "figures.pdf"),
                "name": "figures.pdf",
                "kind": "region",
                "page": 1,
                "frac": [0, 0, 1, 1],
                "el": {"id": "B2", "path": ["B2"]},
            }
        )
        made = self.others_finish_while_stalled(fig, AddRequest(place, "", verdict="채택"))
        self.assertIsInstance(made, OpenPin)
        stored = self.pin(made.core.id)
        self.assertEqual((stored["verdict"], stored["pdf_build"]), ("채택", BUILD1))


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
    "unread loc": EditRequest(base_rev=2, place=UnreadLoc()),
    "lo": EditRequest(base_rev=2, lo=3),
    "hi": EditRequest(base_rev=2, hi=6),
    "scope": EditRequest(base_rev=2, scope="para"),
    "kind": EditRequest(base_rev=2, kind="lines"),
    "kind_req": EditRequest(base_rev=2, kind_req="fix"),
    "suggest": EditRequest(base_rev=2, suggest=Suggestion("a", "b")),
    "suggest null": EditRequest(base_rev=2, suggest=RemoveSuggestion()),
    **{
        name + " null": EditRequest(base_rev=2, note="n", sent_null=frozenset({name}))
        for name in ("loc", "lo", "hi", "scope", "kind", "kind_req")
    },
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

    def test_a_pin_without_a_verdict_reads_a_field_sent_as_null_as_absent(self):
        """On an ordinary pin the note beside target fields sent as null is edited, and nothing else changes."""
        plain = OpenPin.from_record({"id": 3, "file": "/ms/main.tex", "lo": 4, "hi": 5, "note": "n", "rev": 2})
        nulls = EditRequest(base_rev=2, note="m", sent_null=frozenset({"loc", "lo", "hi", "scope", "kind", "kind_req"}))
        self.assertEqual(decide(plain, nulls), decide(plain, EditRequest(base_rev=2, note="m")))

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

    def test_an_unread_loc_on_a_pin_without_a_verdict_is_stale(self):
        """A loc is left unread only for a pin that carried a verdict; a pin without one is not the pin the request was
        read against, so the edit is a conflict and nothing of it applies - even on a closed pin."""
        plain = OpenPin.from_record({"id": 3, "file": "/ms/main.tex", "lo": 4, "hi": 5, "note": "n", "rev": 2})
        done = DonePin.from_record({**plain.record, "done": True})
        for pin in (plain, done):
            with self.subTest(pin=type(pin).__name__):
                self.assertEqual(decide(pin, TARGET_FIELDS["unread loc"]), StaleEdit(pin))


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

    def test_a_target_field_sent_as_null_is_kept_by_name(self):
        """loc, lo, hi, scope, kind and kind_req sent as null have no value but are named in sent_null - alone too,
        since only the pin decides whether that changes anything. A value is not named there, nor is a suggest or
        verdict null, which keep their own meaning."""
        for name in ("loc", "lo", "hi", "scope", "kind", "kind_req"):
            with self.subTest(field=name):
                body = parse_edit({name: None, "base_rev": 0}, ())
                self.assertNotIsInstance(body, InputRejected)
                self.assertEqual(body.request.sent_null, frozenset({name}))
                self.assertEqual(body.request, EditRequest(base_rev=0, sent_null=frozenset({name})))
        sent = parse_edit({"lo": 3, "suggest": None, "verdict": None, "base_rev": 0}, ())
        self.assertEqual(sent.request.sent_null, frozenset())

    def test_a_field_sent_as_null_cannot_also_carry_a_value(self):
        """An EditRequest naming lo as null while holding a lo, or naming a field that is not a target, is a defect."""
        for bad in (dict(lo=3, sent_null=frozenset({"lo"})), dict(sent_null=frozenset({"note"}))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                EditRequest(base_rev=0, **bad)


# The document facts of an edit on a verdict pin: none are needed, since nothing of where the pin points is read.
NO_FACTS = None
NOTHING_TO_CHANGE_REFUSAL = InputRejected(
    "바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).", "nothing_to_change"
)


class EditPlace(unittest.TestCase):
    """parse_edit_place on a verdict pin - one that carries a verdict, or whose edit sends one: where the pin points is
    not read or refused here, so the editing rules see every target field the body sent."""

    def test_a_loc_is_left_unread_and_lines_are_not_refused_on_a_region_pin(self):
        """On a region or a line pin, a loc naming a file that is not there comes back as UnreadLoc and lo/scope/kind
        stay in the request; without a loc there is no place."""
        sent = {"lo": 1, "scope": "para", "kind": "x", "base_rev": 0}
        for region in (True, False):
            for loc in ({"file": "missing.tex", "lo": 1, "hi": 2}, {"page": 99}):
                with self.subTest(region=region, loc=loc):
                    body = parse_edit({**sent, "loc": loc}, ())
                    self.assertEqual(parse_edit_place(body, region, NO_FACTS, verdict=True), UnreadLoc())
                    self.assertEqual((body.request.lo, body.request.scope, body.request.kind), (1, "para", "x"))
            with self.subTest(region=region, loc=None):
                self.assertIsNone(parse_edit_place(parse_edit(sent, ()), region, NO_FACTS, verdict=True))

    def test_an_edit_of_nulls_alone_is_nothing_to_change_on_an_ordinary_pin_only(self):
        """A body naming only a target field as null changes nothing on an ordinary pin, line or region: refused as
        an empty edit. A verdict pin gets no place back, for the editing rules to refuse as verdict_fixed."""
        body = parse_edit({"lo": None, "base_rev": 0}, ())
        for region in (True, False):
            with self.subTest(region=region):
                self.assertEqual(parse_edit_place(body, region, NO_FACTS, verdict=False), NOTHING_TO_CHANGE_REFUSAL)
                self.assertIsNone(parse_edit_place(body, region, NO_FACTS, verdict=True))

    def test_a_body_that_sends_a_verdict_counts_as_a_verdict_pins(self):
        """An ordinary region pin's edit that sends a verdict is not refused for its lines here: the pin it would leave
        is a verdict pin, which the editing rules refuse as verdict_fixed."""
        body = parse_edit({"verdict": "채택", "lo": 1, "loc": {"page": 99}, "base_rev": 0}, ())
        self.assertEqual(parse_edit_place(body, True, NO_FACTS, verdict=False), UnreadLoc())


FIXED = {
    "error": "판정 핀은 판정과 대상을 바꾸지 않습니다 — 새 판정 핀을 찍거나 이 핀을 지웁니다.",
    "reason": "verdict_fixed",
}
NOTHING_TO_CHANGE = {
    "error": "바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).",
    "reason": "nothing_to_change",
}
# Every edit field a verdict pin may not take (D3), by its body name: present with any value - null too - it is
# verdict_fixed on a verdict pin.
NULL_TARGETS = frozenset({"verdict", "loc", "lo", "hi", "scope", "kind", "kind_req", "suggest"})


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

    def test_a_target_field_sent_as_null_is_refused(self):
        """Each field a verdict pin may not take, sent as null - beside a note or alone - is 400 verdict_fixed and
        writes nothing: null names the field as much as a value does, so the note beside it is not written either."""
        for name in NULL_TARGETS:
            for beside in ({"note": "changed"}, {}):
                with self.subTest(field=name, beside=beside):
                    before = self.stored_bytes()
                    self.assertEqual(self.edit({**beside, name: None}, headers=BOB), (400, FIXED))
                    self.assertEqual(self.stored_bytes(), before)

    def test_an_ordinary_pin_takes_a_null_target_field_as_absent(self):
        """On a pin without a verdict a null target field changes nothing, as it always has: beside a note the note is
        written, alone the edit is nothing_to_change. suggest null removes a suggestion and verdict null is refused,
        so neither is one of these."""
        code, d = self.call("POST", "/api/pin", self.body(note="n"), headers=BOB)
        self.assertEqual(code, 200, d)
        pid = d["id"]
        for name in NULL_TARGETS - {"suggest", "verdict"}:
            with self.subTest(field=name):
                rev = self.pin(pid)["rev"]
                body = {"note": "changed " + name, name: None, "base_rev": rev}
                code, got = self.call("POST", "/api/pins/%d/edit" % pid, body, headers=BOB)
                self.assertEqual(code, 200, got)
                self.assertEqual((self.pin(pid)["note"], self.pin(pid)["rev"]), ("changed " + name, rev + 1))
                before = self.stored_bytes()
                got = self.call("POST", "/api/pins/%d/edit" % pid, {name: None, "base_rev": rev + 1}, headers=BOB)
                self.assertEqual(got, (400, NOTHING_TO_CHANGE))
                self.assertEqual(self.stored_bytes(), before)

    def test_a_verdict_sent_to_an_ordinary_pin_is_refused(self):
        """An edit cannot turn a pin into a verdict pin."""
        code, d = self.call("POST", "/api/pin", self.body(note="n"), headers=BOB)
        before = self.stored_bytes()
        got = self.call("POST", "/api/pins/%d/edit" % d["id"], {"verdict": "채택", "base_rev": 0}, headers=BOB)
        self.assertEqual(got, (400, FIXED))
        self.assertEqual(self.stored_bytes(), before)

    def test_a_re_placement_is_refused_before_its_location_is_read(self):
        """A loc naming a file that is not there, or outside the manuscript, is verdict_fixed, not the location's own
        refusal: a verdict pin's loc is never read."""
        for loc in ({"file": "missing.tex", "lo": 1, "hi": 2}, {"file": "/elsewhere/x.tex", "lo": 1, "hi": 2}):
            with self.subTest(loc=loc):
                before = self.stored_bytes()
                self.assertEqual(self.edit({"loc": loc}, headers=BOB), (400, FIXED))
                self.assertEqual(self.stored_bytes(), before)

    def test_line_matching_moves_a_verdict_pin(self):
        """Lines inserted above a verdict pin move it as they move any pin: re-sync is not an edit."""
        text = self.main.read_text(encoding="utf-8")
        self.main.write_text("% one\n% two\n" + text, encoding="utf-8")
        moved = self.pin(self.pid)
        self.assertEqual((moved["lo"], moved["hi"]), (6, 7))
        self.assertEqual(moved["verdict"], "보류")


# Each edit a region pin answers no_source_lines for (lines, a range level or a kind), and re-placements - a valid one,
# one off the page and one naming lines - as bodies sent to a region verdict pin.
REGION_TARGET_EDITS = (
    {"lo": 1, "hi": 2},
    {"lo": 1},
    {"hi": 2},
    {"scope": "para"},
    {"kind": "x"},
    {"loc": {"page": 1, "frac": [0, 0, 0.5, 0.5]}},
    {"loc": {"page": 99, "frac": [0, 0, 1, 1]}},
    {"loc": {"file": "main.tex", "lo": 1, "hi": 2}},
)


class RegionEditOverHttp(VerdictHttpBase):
    """POST /api/pins/{id}/edit on region verdict pins - a whole page of a view-only PDF and a whole figure picked as a
    region on a figure document: every field a verdict pin may not take is verdict_fixed, as on a line verdict pin, and
    not the region pin's own refusal of lines (no_source_lines), whose sentence points at a loc edit."""

    def setUp(self):
        """Documents ms (LaTeX), fig (figure, BUILD1 on screen) and rv (view-only PDF on BUILD1), fig and rv with the
        word file; a whole-page verdict pin on rv and a whole-figure region verdict pin on fig, both by Bob."""
        super().setUp()
        (self.src / "rv").mkdir()
        (self.src / "rv" / "review.pdf").write_bytes(MINI_PDF)
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        self.rv = Doc("rv", "답변", "pdf", self.src / "rv", self.src / "rv" / "review.pdf", paths=ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig, self.rv])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, viewer_map(), pages=2)
        write_build(self.rv, BUILD1, None, pages=3)
        for doc in (self.fig, self.rv):
            verdicts_path(doc).write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")
        self.pdf_page = self.made(
            {"doc": "rv", "page": 1, "frac": [0, 0, 1, 1], "pdf_build": BUILD1, "verdict": "채택"}
        )
        figure = {"id": "B2", "path": ["B2"]}
        self.figure = self.made(
            {"doc": "fig", "page": 1, "frac": [0, 0, 1, 1], "el": figure, "pdf_build": BUILD1, "verdict": "보류"}
        )

    def made(self, body):
        """POST body as editor Bob; the new region pin's id."""
        code, d = self.call("POST", "/api/pin", body, headers=BOB)
        self.assertEqual(code, 200, d)
        self.assertEqual(self.pin(d["id"])["kind"], "region")
        return d["id"]

    def edit(self, pid, body, **who):
        """POST the edit of pin pid with its current rev."""
        return self.call("POST", "/api/pins/%d/edit" % pid, {**body, "base_rev": self.pin(pid)["rev"]}, **who)

    def test_lines_scope_kind_and_re_placements_are_verdict_fixed(self):
        """lo, hi, scope, kind and every loc - valid, off the page or naming lines - are 400 verdict_fixed for a
        person and an agent alike, on both pins, and nothing is written."""
        for pid in (self.pdf_page, self.figure):
            for body in REGION_TARGET_EDITS:
                for who in (dict(headers=BOB), dict(token=self.token)):
                    with self.subTest(pid=pid, body=body, who=who):
                        before = self.stored_bytes()
                        self.assertEqual(self.edit(pid, body, **who), (400, FIXED))
                        self.assertEqual(self.stored_bytes(), before)

    def test_the_note_still_changes(self):
        """Note-level edits go through on a region verdict pin; its verdict and place stay."""
        for pid in (self.pdf_page, self.figure):
            with self.subTest(pid=pid):
                before = self.pin(pid)
                code, d = self.edit(pid, {"note": "이 쪽만"}, headers=BOB)
                self.assertEqual(code, 200, d)
                after = self.pin(pid)
                self.assertEqual(after["note"], "이 쪽만")
                self.assertEqual(
                    {k: after.get(k) for k in ("verdict", "page", "frac", "el")},
                    {k: before.get(k) for k in ("verdict", "page", "frac", "el")},
                )

    def test_an_ordinary_region_pin_keeps_its_refusal_of_lines_unless_the_edit_sends_a_verdict(self):
        """A region pin without a verdict still answers lo with no_source_lines; the same edit with a verdict is
        verdict_fixed, since the pin it would leave is a verdict pin."""
        code, d = self.call("POST", "/api/pin", {"doc": "rv", "page": 2, "frac": [0.1, 0.1, 0.2, 0.2]}, headers=BOB)
        self.assertEqual(code, 200, d)
        code, got = self.edit(d["id"], {"lo": 1}, headers=BOB)
        self.assertEqual((code, got["reason"]), (400, "no_source_lines"))
        before = self.stored_bytes()
        self.assertEqual(self.edit(d["id"], {"lo": 1, "verdict": "채택"}, headers=BOB), (400, FIXED))
        self.assertEqual(self.stored_bytes(), before)

"""Line pins on a Markdown document: no page, no frac, no pdf_build on any path that writes one (ADR-0025 D2), and
suggested edits on them (D8).

A Markdown document (Doc.renders_in_browser) is drawn by the browser from its source, so it has no pages: its line pins
are file, lo, hi, kind, scope and quote alone. The location parsers read the capability from the document's facts
(DocumentFacts.renders_in_browser) and drop the page fields a request sends, as they drop an el outside a figure
document; the pure rules take it as an argument (LinePlace's pages, decide_edit's pages) and every edit of such a pin
removes page fields a record already carries. Every other write of such a pin does too - a claim or unclaim, a reply,
a close, a confirmation, a reopen, a drop into the Trash, a restore and the anchor re-sync - through limn.pins.pages,
with the answer PinContext.has_pages gives for the pin's document. A LaTeX line pin keeps its page fields exactly as
before.

A Markdown document's lines are prose a person writes, so its line pins take a suggested edit, as a LaTeX document's
do: the suggestion gate asks the capability Doc.takes_suggestions, not whether the document is built from LaTeX. A
view-only PDF and a figure document still refuse one.

First the pure rules on records, then the parsers through a real document's facts, then POST /api/pin and POST
/api/pins/{id}/edit over a real server and state folder. No --doc suffix chooses a Markdown document yet, so each test
makes one directly.

Run: uv run pytest -q src/limn/pins/editing/tests/test_markdown_pins.py
"""

import itertools
import json
import os
import unittest

from limn.pins.editing import input as editing_input, location as editing_location
from limn.pins.editing.rules import (
    AddRequest,
    Anchoring,
    EditRequest,
    LinePlace,
    PinEdited,
    SuggestFacts,
    SuggestUnsupported,
    decide_edit,
    decide_new_suggestion,
    evolve_edit,
    new_line_pin,
)
from limn.pins.model import DonePin, OpenPin, ReviewPin
from limn.pins.pages import keep_pages, page_fields_kept
from limn.pins.suggestion import Suggestion
from limn.pins.trash.rules import drop
from limn.runtime import documents
from limn.runtime.documents import Doc
from limn.web.errors import InputRejected

from helpers import Base, jreq, ps, req, split_resp, trash_records
from helpers_access import BOB, AccessBase
from helpers_figure import BUILD1, SCRIPT, b2_map, figure_doc, script_lines, write_build
from helpers_pin_rules import ALICE_PERSON, AT

# The page fields a Markdown pin never keeps: the three a request may send, and the legacy frac_build a record may hold.
PAGE_FIELDS = ("page", "frac", "pdf_build", "frac_build")
# Their values as an older writer, a hand edit or a pin moved in from a generated .tex tab may have left them.
LEGACY = {"page": 1, "frac": [0.1, 0.2, 0.3, 0.4], "pdf_build": "pages", "frac_build": "pages"}
PLAN = (
    "# Plan\n"  # 1
    "\n"  # 2
    "First line of the paragraph.\n"  # 3
    "Second line of the paragraph.\n"  # 4
    "\n"  # 5
    "- item one\n"  # 6
    "- item two\n"  # 7
    "\n"  # 8
    "| a | b |\n"  # 9
    "|---|---|\n"  # 10
    "| 1 | 2 |\n"  # 11
)


def pageless_place(lo=3, hi=4, **extra):
    """A line place on notes/plan.md lines lo..hi of a document without pages."""
    fields = {"file": "/ms/notes/plan.md", "name": "plan.md", "lo": lo, "hi": hi, **extra}
    return LinePlace(fields, frozenset(fields), pages=False)


def markdown_record(**extra):
    """A stored Markdown line pin at L3-L4 of notes/plan.md, as an older writer or a hand edit may have left it: with
    every page field it should not have."""
    record = {
        "file": "/ms/notes/plan.md",
        "name": "plan.md",
        "lo": 3,
        "hi": 4,
        "page": 1,
        "kind": "lines",
        "frac": [0.1, 0.2, 0.3, 0.4],
        "note": "old",
        "id": 5,
        "anchor": {"head": "x"},
        "synced_at": 1.0,
        "pdf_build": "pages",
        "frac_build": "pages",
        "doc": "nt",
        "rev": 2,
    }
    record.update(extra)
    return record


def edited(pages, **fields):
    """The PinEdited fact for Alice at AT on a document with or without pages, with the given changes."""
    base = dict(
        note=None, place=None, lines=None, range_changed=False, scope=None, kind=None, kind_req=None, assignee=None
    )
    base.update(fields)
    return PinEdited(ALICE_PERSON, AT, **base, pages=pages)


def evolve(record, event):
    """evolve_edit of the record by event, with nothing located, anchored or tagged; the record it writes."""
    return evolve_edit(OpenPin.from_record(record), event, None, None, None, None).record


class PagelessPlace(unittest.TestCase):
    """LinePlace(pages=False): the place of a line pin on a document without pages."""

    def test_it_needs_no_page_and_carries_no_page_field(self):
        """Without page it is a valid place that says it has no pages; with page, frac or pdf_build it is refused, so
        a page field cannot reach a Markdown record through a place."""
        place = pageless_place()
        self.assertFalse(place.pages)
        self.assertEqual(list(place.fields), ["file", "name", "lo", "hi"])
        for key, value in (("page", 1), ("frac", [0, 0, 1, 1]), ("pdf_build", "pages")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                pageless_place(**{key: value})

    def test_a_place_with_pages_still_requires_its_page(self):
        """The default is a document with pages: a LaTeX place without page is refused as before."""
        with self.assertRaises(ValueError):
            LinePlace({"file": "/ms/main.tex", "name": "main.tex", "lo": 1, "hi": 2}, frozenset())
        self.assertTrue(
            LinePlace({"file": "/ms/main.tex", "name": "main.tex", "lo": 1, "hi": 2, "page": 1}, frozenset()).pages
        )


class PagelessRecords(unittest.TestCase):
    """The records the pure rules write for a pin on a document without pages."""

    def test_a_new_pin_gets_no_pdf_build(self):
        """new_line_pin records the build on screen for a place with pages; for one without, no pdf_build at all -
        not even null - and no page."""
        place = pageless_place()
        pin = new_line_pin(
            place, AddRequest(place, "n"), 1, AT, {"login": "local"}, (), Anchoring({}, 0), "pages", "nt", None
        )
        for key in PAGE_FIELDS:
            self.assertNotIn(key, pin.record)
        self.assertEqual(list(pin.record)[:5], ["file", "name", "lo", "hi", "kind"])
        paged = LinePlace({"file": "/ms/main.tex", "name": "main.tex", "lo": 4, "hi": 5, "page": 1}, frozenset())
        pin = new_line_pin(
            paged, AddRequest(paged, "n"), 1, AT, {"login": "local"}, (), Anchoring({}, 0), "pages", "ms", None
        )
        self.assertEqual((pin.record["page"], pin.record["pdf_build"]), (1, "pages"))

    def test_every_edit_removes_the_page_fields_a_record_carries(self):
        """A note-only edit, a lo/hi edit and a re-placement of a pin on a document without pages each leave none of
        page, frac, pdf_build and frac_build; an edit that does not re-place it keeps the order of the rest."""
        for name, event in (
            ("note", edited(False, note="new")),
            ("lines", edited(False, lines=(6, 7), range_changed=True)),
            ("re-placement", edited(False, place=pageless_place(6, 7), range_changed=True)),
        ):
            with self.subTest(edit=name):
                out = evolve(markdown_record(), event)
                for key in PAGE_FIELDS:
                    self.assertNotIn(key, out)
                if event.place is None:  # a re-placement writes its location fields anew, at the end
                    self.assertEqual(list(out)[:5], ["file", "name", "lo", "hi", "kind"])

    def test_a_pin_on_a_document_with_pages_keeps_them(self):
        """The same edits of the same record on a document with pages keep page, frac and both builds as before."""
        for name, event in (
            ("note", edited(True, note="new")),
            ("lines", edited(True, lines=(6, 7), range_changed=True)),
        ):
            with self.subTest(edit=name):
                out = evolve(markdown_record(), event)
                self.assertEqual([out[k] for k in PAGE_FIELDS], [1, [0.1, 0.2, 0.3, 0.4], "pages", "pages"], name)

    def test_a_region_pin_keeps_its_region(self):
        """A region pin found on such a document (a hand edit: none is ever made there) keeps its page and frac on a
        note edit, so the edit never leaves a region record the record check would break."""
        region = {"pdf": "/ms/r.pdf", "name": "r.pdf", "kind": "region", "page": 2, "frac": [0, 0, 1, 1], "id": 4}
        out = evolve(region, edited(False, note="new"))
        self.assertEqual((out["page"], out["frac"]), (2, [0, 0, 1, 1]))

    def test_decide_edit_carries_the_documents_pages_into_the_edit(self):
        """decide_edit's pages becomes the accepted edit's; a line place made for the other kind of document is the
        caller's defect."""
        pin = OpenPin.from_record(markdown_record())
        for pages in (True, False):
            event = decide_edit(
                pin, EditRequest(base_rev=2, note="x"), ALICE_PERSON, AT, "10:00", None, 4000, pages=pages
            )
            self.assertIsInstance(event, PinEdited)
            self.assertEqual(event.pages, pages)
        with self.assertRaises(ValueError):
            decide_edit(
                pin, EditRequest(base_rev=2, place=pageless_place()), ALICE_PERSON, AT, "10:00", None, 4000, pages=True
            )


class PageFieldsOnWrite(unittest.TestCase):
    """limn.pins.pages: what every write of a pin keeps of its page fields, given whether its document has pages."""

    def test_a_line_pin_without_pages_loses_them_in_its_state_and_order(self):
        """An open, a review and a done line pin each come back in their state without the four fields, the rest in
        the stored order."""
        for state, extra in ((OpenPin, {}), (ReviewPin, {"done": True, "review": True}), (DonePin, {"done": True})):
            with self.subTest(state=state.__name__):
                record = markdown_record(**extra)
                out = keep_pages(state.from_record(record), False)
                self.assertIsInstance(out, state)
                self.assertEqual(list(out.record), [key for key in record if key not in PAGE_FIELDS])

    def test_with_pages_or_with_none_to_drop_the_pin_is_the_same(self):
        """A document with pages keeps every field, and a pin without page fields is handed back as it is, so its
        stored line keeps its bytes."""
        pin = OpenPin.from_record(markdown_record())
        self.assertIs(keep_pages(pin, True), pin)
        clean = OpenPin.from_record({k: v for k, v in markdown_record().items() if k not in PAGE_FIELDS})
        self.assertIs(keep_pages(clean, False), clean)

    def test_a_region_pin_keeps_its_place(self):
        """A region pin's page and frac are its place: kept on a document without pages too."""
        region = {"pdf": "/ms/r.pdf", "name": "r.pdf", "kind": "region", "page": 2, "frac": [0, 0, 1, 1], "id": 4}
        self.assertEqual(page_fields_kept(region, False), region)
        pin = OpenPin.from_record(region)
        self.assertIs(keep_pages(pin, False), pin)

    def test_the_trash_copy_takes_the_documents_pages(self):
        """drop with pages=False leaves a Trash copy without the four fields; with pages it keeps them."""
        pin = OpenPin.from_record(markdown_record())
        self.assertEqual([k for k in PAGE_FIELDS if k in drop(pin, ALICE_PERSON, AT, pages=False).record], [])
        self.assertEqual([k for k in PAGE_FIELDS if k in drop(pin, ALICE_PERSON, AT).record], list(PAGE_FIELDS))


class MarkdownDocument(Base):
    """The server fixture with a LaTeX document ms and a Markdown document nt (notes/plan.md, PLAN)."""

    def setUp(self):
        """ms and nt, made directly (no --doc suffix chooses a Markdown document yet)."""
        super().setUp()
        (self.src / "notes").mkdir()
        self.md = self.src / "notes" / "plan.md"
        self.md.write_text(PLAN, encoding="utf-8")
        self.ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        self.nt = Doc("nt", "계획", "markdown", self.src / "notes", self.md, paths=ps.APP.C.paths)
        ps.APP.set_docs([self.ms, self.nt])
        self.addCleanup(ps.APP.set_docs, None)

    def post(self, path, body):
        """POST path with a JSON body as the local agent: (status, parsed body)."""
        code, _, out = split_resp(self.talk(jreq("POST", path, body)))
        return code, json.loads(out)

    def get_pin(self, pid):
        """GET /api/pins/{pid}'s pin."""
        code, _, out = split_resp(self.talk(req("GET", "/api/pins/%d" % pid)))
        self.assertEqual(code, 200, out)
        return json.loads(out)["pin"]

    def make(self, **body):
        """A new pin made as the local agent; its id."""
        code, d = self.post("/api/pin", body)
        self.assertEqual(code, 200, d)
        return d["id"]

    def make_md(self, lo=3, hi=4, **extra):
        """A new pin on lines lo-hi of notes/plan.md; its id."""
        return self.make(doc="nt", file=str(self.md), lo=lo, hi=hi, note="n", **extra)

    def stored_with(self, pid, **fields):
        """Rewrite pin pid's stored record with fields added at its end, as an older writer or a hand edit could
        have left it."""
        lines = ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            rec = json.loads(line)
            if rec.get("id") == pid:
                rec.update(fields)
            out.append(json.dumps(rec, ensure_ascii=False))
        ps.APP.C.pins_jsonl.write_text("".join(t + "\n" for t in out), encoding="utf-8")

    def assert_pageless(self, pid):
        """Pin pid's record and its GET answer hold none of the page fields."""
        record, shown = self.pin(pid), self.get_pin(pid)
        for key in PAGE_FIELDS:
            self.assertNotIn(key, record)
            self.assertNotIn(key, shown)


class PagelessParsing(MarkdownDocument):
    """The location parsers read the capability from the Markdown document's own facts (DocumentFacts)."""

    def test_the_facts_of_a_markdown_document_say_it_is_drawn_in_the_browser(self):
        """DocumentFacts.renders_in_browser is the document's capability: true for nt, false for ms."""
        self.assertTrue(ps.APP.document_facts(self.nt).renders_in_browser)
        self.assertFalse(ps.APP.document_facts(self.ms).renders_in_browser)

    def test_parse_loc_drops_the_page_fields_unread(self):
        """page, frac and pdf_build are dropped without being checked - malformed ones too, as an el is outside a
        figure document - and the record has none of them; the same body on ms keeps them."""
        body = {"file": str(self.md), "lo": 3, "hi": 4, "page": 1, "frac": [0, 0, 1, 1], "pdf_build": "pages"}
        nt, ms = ps.APP.document_facts(self.nt), ps.APP.document_facts(self.ms)
        loc = editing_location.parse_loc(body, nt)
        self.assertIsNone(loc.page)
        self.assertEqual(list(loc.to_record()), ["file", "name", "lo", "hi"])
        for bad in ({"page": "x"}, {"page": 0}, {"frac": "box"}, {"pdf_build": "../x"}):
            with self.subTest(bad=bad):
                self.assertEqual(
                    list(editing_location.parse_loc({**body, **bad}, nt).to_record()), ["file", "name", "lo", "hi"]
                )
        latex = editing_location.parse_loc({**body, "file": str(self.main)}, ms).to_record()
        self.assertEqual((latex["page"], latex["frac"], latex["pdf_build"]), (1, [0.0, 0.0, 1.0, 1.0], "pages"))

    def test_an_add_and_an_edit_place_are_pageless_and_name_no_page_field(self):
        """parse_add and parse_edit_place give a place without pages whose named set holds no field it dropped; a
        re-placement that sends frac records no build either."""
        nt = ps.APP.document_facts(self.nt)
        sent = {"file": str(self.md), "lo": 3, "hi": 4, "page": 2, "frac": [0, 0, 1, 1], "pdf_build": "pages"}
        request = editing_input.parse_add({**sent, "note": "n"}, (), nt)
        self.assertIsInstance(request, AddRequest)
        self.assertFalse(request.place.pages)
        self.assertEqual(request.place.named & set(PAGE_FIELDS), frozenset())
        body = editing_input.parse_edit({"loc": sent, "base_rev": 0}, ())
        place = editing_input.parse_edit_place(body, False, nt, verdict=False)
        self.assertIsInstance(place, LinePlace)
        self.assertFalse(place.pages)
        self.assertEqual(list(place.fields), ["file", "name", "lo", "hi"])
        self.assertEqual(place.named & set(PAGE_FIELDS), frozenset())
        self.assertNotIsInstance(place, InputRejected)


class PagelessPinsOverHttp(MarkdownDocument):
    """POST /api/pin and POST /api/pins/{id}/edit on the Markdown document store no page field, sent or inherited."""

    def test_page_fields_sent_with_a_new_pin_are_not_stored(self):
        """An agent's habitual page: 1 with frac and pdf_build is accepted and none of them is stored or answered."""
        pid = self.make_md(page=1, frac=[0.1, 0.1, 0.2, 0.2], pdf_build="pages")
        self.assert_pageless(pid)
        self.assertEqual(list(self.pin(pid))[:5], ["file", "name", "lo", "hi", "kind"])

    def test_a_new_pin_without_them_gets_no_pdf_build(self):
        """A pin that sent no build gets none - not the build on screen and not null."""
        pid = self.make_md()
        self.assertNotIn("pdf_build", self.pin(pid))
        self.assert_pageless(pid)

    def test_page_fields_sent_with_a_re_placement_are_not_stored(self):
        """A loc with page, frac and pdf_build moves the pin to its lines and stores none of the three."""
        pid = self.make_md()
        code, d = self.post(
            "/api/pins/%d/edit" % pid,
            {
                "base_rev": 0,
                "loc": {
                    "file": str(self.md),
                    "lo": 6,
                    "hi": 7,
                    "page": 2,
                    "frac": [0.1, 0.1, 0.2, 0.2],
                    "pdf_build": "pages",
                },
            },
        )
        self.assertEqual(code, 200, d)
        self.assertEqual((self.pin(pid)["lo"], self.pin(pid)["hi"]), (6, 7))
        self.assert_pageless(pid)

    def test_a_stored_record_with_page_fields_loses_them_on_a_re_placement_and_on_a_note_edit(self):
        """A record that carries all four - a PoC's page: 1, a hand edit, a pin moved in from a generated .tex tab -
        loses them on a re-placement without them and on an edit of its note alone."""
        moved, noted = self.make_md(), self.make_md(6, 7)
        legacy = {"page": 1, "frac": [0.1, 0.2, 0.3, 0.4], "pdf_build": "pages", "frac_build": "pages"}
        self.stored_with(moved, **legacy)
        self.stored_with(noted, **legacy)
        code, d = self.post(
            "/api/pins/%d/edit" % moved, {"base_rev": 0, "loc": {"file": str(self.md), "lo": 9, "hi": 11}}
        )
        self.assertEqual(code, 200, d)
        code, d = self.post("/api/pins/%d/edit" % noted, {"base_rev": 0, "note": "다시"})
        self.assertEqual(code, 200, d)
        self.assertEqual(self.pin(noted)["note"], "다시")
        self.assert_pageless(moved)
        self.assert_pageless(noted)

    def test_a_latex_line_pin_keeps_its_page_fields_as_before(self):
        """On ms the sent page, frac and pdf_build are stored; a re-placement that names neither page nor frac keeps
        them, and a note edit keeps all three."""
        pid = self.make(
            doc="ms", file=str(self.main), lo=4, hi=5, page=2, frac=[0.1, 0.1, 0.2, 0.2], pdf_build="pages", note="n"
        )
        kept = ([0.1, 0.1, 0.2, 0.2], "pages")
        self.assertEqual((self.pin(pid)["page"], self.pin(pid)["frac"], self.pin(pid)["pdf_build"]), (2, *kept))
        code, d = self.post(
            "/api/pins/%d/edit" % pid, {"base_rev": 0, "loc": {"file": str(self.main), "lo": 8, "hi": 9}}
        )
        self.assertEqual(code, 200, d)
        code, d = self.post("/api/pins/%d/edit" % pid, {"base_rev": 1, "note": "다시"})
        self.assertEqual(code, 200, d)
        self.assertEqual((self.pin(pid)["page"], self.pin(pid)["frac"], self.pin(pid)["pdf_build"]), (2, *kept))


class PagelessOnEveryWrite(MarkdownDocument, AccessBase):
    """Not an edit alone: every write of a Markdown line pin whose record still carries page, frac, pdf_build and
    frac_build drops all four (ADR-0025 D2) - a claim, an unclaim, a reply, a reopening reply, a person's close, an
    agent's close with changes, a confirmation, a reopen, a drop (its Trash copy), a restore and the anchor re-sync. A
    LaTeX line pin keeps them on each of those writes, and a refused write writes nothing. Records are read from
    pins.jsonl as stored, without the re-sync a read through the store would run."""

    def raw(self, pid):
        """Pin pid's record as pins.jsonl holds it now, read without a re-sync."""
        for line in ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("id") == pid:
                return record
        self.fail("pin #%d is not in pins.jsonl" % pid)

    def page_fields(self, record):
        """The page fields record carries, with their values."""
        return {key: record[key] for key in PAGE_FIELDS if key in record}

    def legacy(self, pid):
        """Give pin pid's stored record the four page fields, as LEGACY has them."""
        self.stored_with(pid, **LEGACY)
        self.assertEqual(self.page_fields(self.raw(pid)), LEGACY)

    def act(self, pid, action, body=None, headers=None):
        """POST /api/pins/{pid}/{action} - as the loopback agent, or as the person headers name - answered 200."""
        code, d = self.call("POST", "/api/pins/%d/%s" % (pid, action), body or {}, headers)
        self.assertEqual(code, 200, d)
        return d

    def assert_pageless_now(self, pid):
        """Pin pid's stored record carries no page field."""
        self.assertEqual(self.page_fields(self.raw(pid)), {})

    def test_a_claim(self):
        """POST /claim on a legacy record drops the four fields with the claim it places."""
        pid = self.make_md()
        self.legacy(pid)
        self.act(pid, "claim")
        self.assertIn("claimed_by", self.raw(pid))
        self.assert_pageless_now(pid)

    def test_an_unclaim(self):
        """POST /unclaim of a claimed legacy record drops them with the claim."""
        pid = self.make_md()
        self.act(pid, "claim")
        self.legacy(pid)
        self.act(pid, "unclaim")
        self.assertNotIn("claimed_by", self.raw(pid))
        self.assert_pageless_now(pid)

    def test_a_reply_in_each_state(self):
        """An agent's reply - it never reopens - drops them on an open legacy record, on one awaiting review (an
        agent's close) and on a done one (a person's close); the pin keeps its state and the reply is its last
        thread entry."""
        for state, closer in (("open", None), ("review", {}), ("done", BOB)):
            with self.subTest(state=state):
                pid = self.make_md()
                if closer is not None:
                    self.act(pid, "close", {}, closer or None)
                self.legacy(pid)
                self.act(pid, "reply", {"text": "확인했습니다"})
                record = self.raw(pid)
                shown = "review" if record.get("review") else "done" if record.get("done") else "open"
                self.assertEqual((shown, record["thread"][-1]["text"]), (state, "확인했습니다"))
                self.assert_pageless_now(pid)

    def test_a_reopening_reply(self):
        """A person's reply on a legacy record awaiting review reopens it and drops them."""
        pid = self.make_md()
        self.act(pid, "close")
        self.legacy(pid)
        self.act(pid, "reply", {"text": "다시 봐 주세요"}, BOB)
        self.assertIs(self.raw(pid)["done"], False)
        self.assert_pageless_now(pid)

    def test_a_persons_close(self):
        """A person's close of a legacy record (done at once) drops them."""
        pid = self.make_md()
        self.legacy(pid)
        self.act(pid, "close", {"reply": "고쳤습니다"}, BOB)
        self.assertNotIn("review", self.raw(pid))
        self.assert_pageless_now(pid)

    def test_an_agents_close_with_changes(self):
        """An agent's close with changes (awaiting review) drops them; the changes are stored."""
        pid = self.make_md()
        self.legacy(pid)
        self.act(pid, "close", {"reply": "고쳤습니다", "changes": [{"file": str(self.md), "lo": 3, "hi": 3}]})
        record = self.raw(pid)
        self.assertEqual((record["review"], record["changes"][0]["lo"]), (True, 3))
        self.assert_pageless_now(pid)

    def test_a_confirmation(self):
        """A person's confirmation of a legacy record awaiting review drops them."""
        pid = self.make_md()
        self.act(pid, "close")
        self.legacy(pid)
        self.act(pid, "confirm", {}, BOB)
        self.assertIn("confirmed_by", self.raw(pid))
        self.assert_pageless_now(pid)

    def test_a_reopen(self):
        """POST /reopen of a closed legacy record drops them."""
        pid = self.make_md()
        self.act(pid, "close")
        self.legacy(pid)
        self.act(pid, "reopen", {"reason": "다시"})
        self.assertIs(self.raw(pid)["done"], False)
        self.assert_pageless_now(pid)

    def test_a_drop(self):
        """POST /drop of a legacy record leaves a Trash copy without them."""
        pid = self.make_md()
        self.legacy(pid)
        self.act(pid, "drop")
        (copy,) = [entry for entry in trash_records() if entry["id"] == pid]
        self.assertEqual(self.page_fields(copy), {})

    def test_a_restore(self):
        """POST /restore of a Trash copy that still carries them brings the pin back without them."""
        pid = self.make_md()
        self.act(pid, "drop")
        path = ps.APP.pin_store().files.dropped
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        path.write_text(
            "".join(json.dumps({**e, **LEGACY} if e["id"] == pid else e, ensure_ascii=False) + "\n" for e in entries),
            encoding="utf-8",
        )
        self.assertEqual(self.page_fields(trash_records()[-1]), LEGACY)
        self.act(pid, "restore")
        self.assert_pageless_now(pid)

    def test_the_anchor_resync(self):
        """Two lines added above a legacy record's lines move it on the next read (GET /api/pins re-syncs and writes
        the pin), and that write drops them."""
        pid = self.make_md(6, 7)
        self.legacy(pid)
        synced_at = self.raw(pid)["synced_at"]
        self.md.write_text("# Intro\n\n" + PLAN, encoding="utf-8")
        os.utime(self.md, (synced_at + 5, synced_at + 5))
        code, _, out = split_resp(self.talk(req("GET", "/api/pins")))
        self.assertEqual(code, 200, out)
        self.assertEqual((self.raw(pid)["lo"], self.raw(pid)["hi"]), (8, 9))
        self.assert_pageless_now(pid)

    def test_a_latex_line_pin_keeps_them_on_every_write(self):
        """The same writes of a LaTeX line pin carrying the four fields keep them, the Trash copy included."""
        pid = self.make(doc="ms", file=str(self.main), lo=4, hi=5, note="n")
        self.legacy(pid)
        for action, body, headers in (
            ("claim", {}, None),
            ("unclaim", {}, None),
            ("reply", {"text": "확인"}, None),
            ("close", {}, None),
            ("confirm", {}, BOB),
            ("reopen", {"reason": "다시"}, None),
            ("drop", {}, None),
        ):
            with self.subTest(action=action):
                self.act(pid, action, body, headers)
                record = trash_records()[-1] if action == "drop" else self.raw(pid)
                self.assertEqual(self.page_fields(record), LEGACY)
        self.act(pid, "restore")
        self.assertEqual(self.page_fields(self.raw(pid)), LEGACY)

    def test_a_refused_write_writes_nothing(self):
        """A claim of a closed legacy record is refused (409) and its record keeps the four fields: only a write
        drops them."""
        pid = self.make_md()
        self.act(pid, "close")
        self.legacy(pid)
        code, d = self.call("POST", "/api/pins/%d/claim" % pid, {})
        self.assertEqual(code, 409, d)
        self.assertEqual(self.page_fields(self.raw(pid)), LEGACY)


PARAGRAPH = "First line of the paragraph.\nSecond line of the paragraph."  # PLAN lines 3-4


class MarkdownSuggestionRules(unittest.TestCase):
    """The pure suggestion rules take the document's capability, not whether it is LaTeX."""

    def test_a_document_that_takes_suggestions_accepts_one_on_its_lines(self):
        """decide_new_suggestion with takes_suggestions accepts a suggestion on a place without pages whose base is its
        lines; without the capability it is unsupported. decide_edit reads the capability from SuggestFacts."""
        lines = tuple(PLAN.splitlines())
        suggestion = Suggestion(PARAGRAPH, "One line.")
        self.assertEqual(decide_new_suggestion(suggestion, pageless_place(), True, lines), suggestion)
        self.assertEqual(decide_new_suggestion(suggestion, pageless_place(), False, lines), SuggestUnsupported())
        pin = OpenPin.from_record(markdown_record())
        request = EditRequest(base_rev=2, suggest=suggestion)
        for takes, accepted in ((True, True), (False, False)):
            with self.subTest(takes_suggestions=takes):
                event = decide_edit(
                    pin, request, ALICE_PERSON, AT, "10:00", None, 4000, SuggestFacts(takes, lines), pages=False
                )
                self.assertEqual(isinstance(event, PinEdited), accepted, event)


class MarkdownSuggestionsOverHttp(MarkdownDocument):
    """POST /api/pin and POST /api/pins/{id}/edit with a suggestion on the Markdown document, beside a view-only PDF
    and a figure document that still refuse one."""

    def test_a_new_markdown_pin_stores_its_suggestion_and_reads_ready(self):
        """A suggestion on notes/plan.md L3-L4 whose base is those lines is stored last in the record and its state
        is ready; the pin keeps no page field."""
        pid = self.make_md(suggest={"base": PARAGRAPH, "text": "One line of **the** paragraph."})
        self.assertEqual(self.pin(pid)["suggest"], {"base": PARAGRAPH, "text": "One line of **the** paragraph."})
        self.assertEqual(list(self.pin(pid))[-1], "suggest")
        self.assertEqual(self.get_pin(pid)["suggest_state"], "ready")
        self.assert_pageless(pid)

    def test_an_edit_sets_a_suggestion_on_a_markdown_pin(self):
        """An edit setting a suggestion on a Markdown pin is accepted and answered with its state; a base written
        against other text is still 409 suggest_base_changed with the lines' current text."""
        pid = self.make_md(6, 7)
        code, d = self.post(
            "/api/pins/%d/edit" % pid, {"base_rev": 0, "suggest": {"base": "- item one\n- item two", "text": "- one"}}
        )
        self.assertEqual(code, 200, d)
        self.assertEqual((d["pin"]["suggest"]["text"], d["pin"]["suggest_state"]), ("- one", "ready"))
        code, d = self.post("/api/pins/%d/edit" % pid, {"base_rev": 1, "suggest": {"base": "- item", "text": "x"}})
        self.assertEqual((code, d["reason"], d["current"]), (409, "suggest_base_changed", "- item one\n- item two"))

    def test_a_view_only_or_figure_document_still_refuses_one(self):
        """With a view-only PDF and a figure document served too, their pins are still 400 suggest_unsupported and
        nothing of them is stored, while the Markdown pin beside them takes its suggestion."""
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        fig = figure_doc(self.src, ps.APP.C.paths)
        rv = Doc("rv", "리뷰", "pdf", self.src, self.src / "review.pdf", paths=ps.APP.C.paths)
        ps.APP.set_docs([self.ms, self.nt, fig, rv])
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
        pid = self.make_md(suggest={"base": PARAGRAPH, "text": "x"})
        self.assertEqual(self.pin(pid)["suggest"]["text"], "x")


class FileOnlyRouting(Base):
    """A request that names only a file (an agent's curl, no doc key) goes to the document that holds it
    (limn.runtime.documents.doc_for_file). A Markdown document is one file: it holds its own file alone, whichever
    folder it shares - so its .md goes to it and not to a LaTeX document in the same folder, and a LaTeX file beside
    or below it still goes to the LaTeX document."""

    def setUp(self):
        """ms (main.tex) and nt (plan.md) in the same manuscript folder, ms listed first; notes/ holds a second
        Markdown document nt2 (notes/todo.md) beside a .tex and an .md that no document registers."""
        super().setUp()
        self.plan = self.src / "plan.md"
        self.plan.write_text(PLAN, encoding="utf-8")
        (self.src / "notes").mkdir()
        self.todo = self.src / "notes" / "todo.md"
        self.todo.write_text("- one\n- two\n", encoding="utf-8")
        (self.src / "notes" / "part.tex").write_text("a\nb\n", encoding="utf-8")
        (self.src / "notes" / "loose.md").write_text("a\nb\n", encoding="utf-8")
        self.ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        self.nt = Doc("nt", "계획", "markdown", self.src, self.plan, paths=ps.APP.C.paths)
        self.nt2 = Doc("nt2", "할 일", "markdown", self.src / "notes", self.todo, paths=ps.APP.C.paths)
        self.docs = [self.ms, self.nt, self.nt2]
        ps.APP.set_docs(self.docs)
        self.addCleanup(ps.APP.set_docs, None)

    def test_a_markdown_documents_own_file_goes_to_it(self):
        """plan.md (relative or absolute) goes to nt although ms is as deep and listed first; notes/todo.md to nt2."""
        self.assertIs(documents.doc_for_file(self.docs, self.src, "plan.md"), self.nt)
        self.assertIs(documents.doc_for_file(self.docs, self.src, str(self.plan)), self.nt)
        self.assertIs(documents.doc_for_file(self.docs, self.src, "notes/todo.md"), self.nt2)

    def test_other_files_never_go_to_a_markdown_document(self):
        """main.tex, a .tex in a Markdown document's folder and an .md no document registers go to the LaTeX
        document, as before Markdown documents existed."""
        for name in ("main.tex", "notes/part.tex", "notes/loose.md"):
            with self.subTest(file=name):
                self.assertIs(documents.doc_for_file(self.docs, self.src, name), self.ms)

    def test_a_pin_that_names_only_the_md_file_is_a_markdown_pin(self):
        """POST /api/pin with file plan.md and no doc makes a pin of nt without page fields; one on main.tex is ms's
        with its page."""
        code, _, out = split_resp(self.talk(jreq("POST", "/api/pin", {"file": "plan.md", "lo": 3, "hi": 4, "page": 1})))
        self.assertEqual(code, 200, out)
        md = self.pin(json.loads(out)["id"])
        self.assertEqual(md["doc"], "nt")
        for key in PAGE_FIELDS:
            self.assertNotIn(key, md)
        code, _, out = split_resp(self.talk(jreq("POST", "/api/pin", {"file": "main.tex", "lo": 4, "hi": 5})))
        self.assertEqual(code, 200, out)
        tex = self.pin(json.loads(out)["id"])
        self.assertEqual((tex["doc"], tex["page"]), ("ms", 1))


class SameFolderRegistrationOrder(Base):
    """A LaTeX document, a figure document and a Markdown document all in the manuscript folder: a request that names
    only the Markdown file goes to the Markdown document whichever order the three are registered in. At equal depth
    the folder rule alone would let the first-listed LaTeX document, or the figure document (which an .md file
    prefers as a file without a LaTeX suffix), take it; the exact match on the Markdown document's own file comes
    first. Every other file keeps the folder rule's answer in every order."""

    def setUp(self):
        """ms (main.tex), fig (figures.limnmap.json, drawn by plot.py) and nt (plan.md) over self.src, plus an .md no
        document registers."""
        super().setUp()
        self.plan = self.src / "plan.md"
        self.plan.write_text(PLAN, encoding="utf-8")
        (self.src / "plot.py").write_text("\n".join(script_lines()) + "\n", encoding="utf-8")
        (self.src / "loose.md").write_text("a\nb\n", encoding="utf-8")
        (self.src / "figures.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        (self.src / "figures.limnmap.json").write_text(json.dumps(b2_map(), ensure_ascii=False), encoding="utf-8")
        self.ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        self.fig = Doc("fig", "그림", "figure", self.src, self.src / "figures.limnmap.json", paths=ps.APP.C.paths)
        self.nt = Doc("nt", "계획", "markdown", self.src, self.plan, paths=ps.APP.C.paths)
        self.addCleanup(ps.APP.set_docs, None)

    def orders(self):
        """Every registration order of the three documents."""
        return list(itertools.permutations((self.ms, self.fig, self.nt)))

    def test_every_order_routes_each_file_the_same_way(self):
        """plan.md (relative or absolute) goes to nt, main.tex to ms, plot.py and the unregistered loose.md to fig - in
        all six orders."""
        want = {
            "plan.md": self.nt,
            str(self.plan): self.nt,
            "main.tex": self.ms,
            "plot.py": self.fig,
            "loose.md": self.fig,
        }
        for order in self.orders():
            for name, doc in want.items():
                with self.subTest(order=[d.key for d in order], file=name):
                    self.assertIs(documents.doc_for_file(list(order), self.src, name), doc)

    def test_a_pin_on_the_md_file_is_the_markdown_documents_in_every_order(self):
        """POST /api/pin with file plan.md and no doc, sent with page: 1 out of habit, is a pin of nt without page
        fields, whether nt is registered first, between or last."""
        for order in self.orders():
            with self.subTest(order=[d.key for d in order]):
                ps.APP.set_docs(list(order))
                body = {"file": "plan.md", "lo": 3, "hi": 4, "page": 1, "note": "n"}
                code, _, out = split_resp(self.talk(jreq("POST", "/api/pin", body)))
                self.assertEqual(code, 200, out)
                record = self.pin(json.loads(out)["id"])
                self.assertEqual(record["doc"], "nt")
                for key in PAGE_FIELDS:
                    self.assertNotIn(key, record)

"""Line pins on a Markdown document: no page, no frac, no pdf_build on any path that writes one (ADR-0025 D2).

A Markdown document (Doc.renders_in_browser) is drawn by the browser from its source, so it has no pages: its line pins
are file, lo, hi, kind, scope and quote alone. The location parsers read the capability from the document's facts
(DocumentFacts.renders_in_browser) and drop the page fields a request sends, as they drop an el outside a figure
document; the pure rules take it as an argument (LinePlace's pages, decide_edit's pages) and every edit of such a pin
removes page fields a record already carries. A LaTeX line pin keeps its page fields exactly as before.

First the pure rules on records, then the parsers through a real document's facts, then POST /api/pin and POST
/api/pins/{id}/edit over a real server and state folder. No --doc suffix chooses a Markdown document yet, so each test
makes one directly.

Run: uv run pytest -q src/limn/pins/editing/tests/test_markdown_pins.py
"""

import json
import unittest

from limn.pins.editing import input as editing_input, location as editing_location
from limn.pins.editing.rules import (
    AddRequest,
    Anchoring,
    EditRequest,
    LinePlace,
    PinEdited,
    decide_edit,
    evolve_edit,
    new_line_pin,
)
from limn.pins.model import OpenPin
from limn.runtime.documents import Doc
from limn.web.errors import InputRejected

from helpers import Base, jreq, ps, req, split_resp
from helpers_pin_rules import ALICE_PERSON, AT

# The page fields a Markdown pin never keeps: the three a request may send, and the legacy frac_build a record may hold.
PAGE_FIELDS = ("page", "frac", "pdf_build", "frac_build")
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

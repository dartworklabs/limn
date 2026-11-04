"""pins.md for a Markdown document (ADR-0025 D2, D3): a line pin without a page, and the document's section.

A Markdown document is drawn by the browser from its source, so its line pins have no page: the page column shows
`—` for any line pin without one. First the renderer on its own (PinsMdInput values), then pins.md as the server
writes it after a Markdown pin is made. No --doc suffix chooses a Markdown document yet, so each test makes one
directly.

Run: uv run pytest -q src/limn/pins/listing/tests/test_markdown_pins.py
"""

import json
import unittest

from limn.pins.listing.render import DocHeading, PinFacts, PinsMdInput, pins_md_text
from limn.runtime.documents import Doc

from helpers import Base, jreq, ps, split_resp

MAIN = DocHeading("main", "본문", "main.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
T = 1_790_000_000.0


def facts(**extra):
    """PinFacts of a plain line pin in the first document at main.tex, with nothing decided about it."""
    base = dict(
        doc_key="main", location="main.tex", line_len=None, badge="", reopened=False, addressed=(), fyi=(), round=()
    )
    base.update(extra)
    return PinFacts(**base)


def page(rows, pin_facts=None, docs=(MAIN,)):
    """A PinsMdInput over rows: loopback, frozen clock; facts default to facts() for every row."""
    return PinsMdInput(
        rows=rows,
        facts=pin_facts if pin_facts is not None else {r["id"]: facts() for r in rows},
        base=None,
        port=18999,
        manuscript="/ms",
        label="원고",
        repo=None,
        docs=docs,
        people={},
        now=T,
        updated="2026-09-26 10:00",
        token_file=None,
    )


def line_pin(pid, **extra):
    """An open line pin at L4-L5 of main.tex with a note."""
    record = {"id": pid, "file": "/ms/main.tex", "lo": 4, "hi": 5, "page": 1, "note": "note %d" % pid, "kind": "lines"}
    record.update(extra)
    return record


def row_of(md, pid):
    """The cells of pin pid's row in the open table of pins.md, stripped."""
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| ") and cells[0].split(" · ")[0] == str(pid):
            return cells
    raise AssertionError("no row for pin %d in:\n%s" % (pid, md))


class PageColumn(unittest.TestCase):
    """The page column of the open table."""

    def test_a_line_pin_without_a_page_shows_a_dash(self):
        """A line pin with no page - a Markdown document's - shows `—`, not 0; one with a page shows it as before."""
        pageless = line_pin(1)
        del pageless["page"]
        md = pins_md_text(page([pageless, line_pin(2, page=3)]))
        self.assertEqual(row_of(md, 1)[1], "—")
        self.assertEqual(row_of(md, 2)[1], "3")

    def test_a_region_pin_keeps_its_page(self):
        """A view-only PDF's region pin always has its page, and the column shows it."""
        rv = DocHeading("rv", "리뷰", "review.pdf", view_only=True, builds_from_source=False, head=None, built_at=None)
        region = {"id": 1, "pdf": "/ms/review.pdf", "page": 2, "frac": [0.1, 0.1, 0.2, 0.2], "kind": "region"}
        md = pins_md_text(page([region], {1: facts(doc_key="rv", location="")}, docs=(MAIN, rv)))
        self.assertEqual(row_of(md, 1)[1], "2")


class MarkdownPinsMd(Base):
    """pins.md as the server writes it, with a LaTeX document ms and a Markdown document nt (notes/plan.md)."""

    def setUp(self):
        """ms and nt, made directly."""
        super().setUp()
        (self.src / "notes").mkdir()
        self.md = self.src / "notes" / "plan.md"
        self.md.write_text("# Plan\n\nFirst line.\nSecond line.\n\n## Next\n\nMore.\n", encoding="utf-8")
        self.ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        self.nt = Doc("nt", "계획", "markdown", self.src / "notes", self.md, paths=ps.APP.C.paths)
        ps.APP.set_docs([self.ms, self.nt])
        self.addCleanup(ps.APP.set_docs, None)

    def make(self, **body):
        """A new pin made as the local agent; its id."""
        code, _, out = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        d = json.loads(out)
        self.assertEqual(code, 200, d)
        return d["id"]

    def pins_md(self):
        """pins.md as written after the last change."""
        return ps.APP.C.pins_md.read_text(encoding="utf-8")

    def test_a_markdown_pin_is_listed_with_a_dash_for_its_page(self):
        """An agent's pin on notes/plan.md L3-L4 sent with page: 1 is listed with `—` in the page column and its file
        and lines in the location column; a LaTeX pin keeps its page."""
        md_pin = self.make(doc="nt", file=str(self.md), lo=3, hi=4, page=1, note="고쳐 줘")
        tex_pin = self.make(doc="ms", file=str(self.main), lo=4, hi=5, page=2, note="n")
        text = self.pins_md()
        self.assertEqual(row_of(text, md_pin)[1:3], ["—", "`notes/plan.md L3-L4`"])
        self.assertEqual(row_of(text, tex_pin)[1], "2")

"""pins.md for a Markdown document (ADR-0025 D2, D3): a line pin without a page, its range, and the document's section.

A Markdown document is drawn by the browser from its source, so its line pins have no page: the page column shows
`—` for any line pin without one. Its ladder's rungs are the rendered block (scope `block`, kind `md:<block>`) and the
heading's section (scope `section`, kind `md:section`), which the range column names; its section title says it is a
Markdown document. First the renderer on its own (PinsMdInput values), then pins.md as the server writes it after a
Markdown pin is made. No --doc suffix chooses a Markdown document yet, so each test makes one directly.

Run: uv run pytest -q src/limn/pins/listing/tests/test_markdown_pins.py
"""

import json
import unittest

from limn.pins.listing.render import DocHeading, PinFacts, PinsMdInput, pins_md_text
from limn.runtime.documents import Doc

from helpers import SKILL_KO, SKILL_MD, Base, jreq, ps, split_resp

MAIN = DocHeading("main", "본문", "main.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
NOTES = DocHeading(
    "nt", "계획", "notes/plan.md", view_only=False, builds_from_source=False, head=None, built_at=None,
    renders_in_browser=True,
)  # fmt: skip
MARKDOWN_TITLE = "## 계획 · `nt` · `notes/plan.md` — Markdown(쪽 없음)"
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


class RangeColumn(unittest.TestCase):
    """The range column names a Markdown rung: the block's kind, or the section."""

    def test_a_block_shows_its_markdown_kind_and_a_section_shows_md_section(self):
        """scope block with kind md:<block> shows that kind; scope section shows md:section; a block without an md:
        kind shows the rung's own name rather than a LaTeX word."""
        rows = [
            line_pin(1, scope="block", kind="md:table"),
            line_pin(2, scope="block", kind="md:item"),
            line_pin(3, scope="section", kind="md:section"),
            line_pin(4, scope="section", kind="lines"),
            line_pin(5, scope="block", kind="lines"),
        ]
        md = pins_md_text(page(rows))
        self.assertEqual(
            [row_of(md, pid)[3] for pid in (1, 2, 3, 4, 5)],
            ["md:table", "md:item", "md:section", "md:section", "block"],
        )

    def test_the_latex_rungs_read_as_before(self):
        """para, env, raw and lines keep their labels."""
        rows = [
            line_pin(1, scope="para", kind="paragraph"),
            line_pin(2, scope="env", kind="env:figure"),
            line_pin(3, scope="raw"),
            line_pin(4, scope="lines"),
        ]
        md = pins_md_text(page(rows))
        self.assertEqual([row_of(md, pid)[3] for pid in (1, 2, 3, 4)], ["paragraph", "env:figure", "lines", "lines"])


class MarkdownSection(unittest.TestCase):
    """The section of a Markdown document."""

    def test_its_title_says_markdown_and_it_has_no_build_line(self):
        """The section title ends with — Markdown(쪽 없음); with no build there is no 기준 line; the LaTeX section's
        title is unchanged."""
        pin = line_pin(1, file="/ms/notes/plan.md")
        del pin["page"]
        md = pins_md_text(page([pin, line_pin(2)], {1: facts(doc_key="nt"), 2: facts()}, docs=(MAIN, NOTES)))
        lines = md.splitlines()
        self.assertIn(MARKDOWN_TITLE, lines)
        self.assertIn("## 본문 · `main` · `main.tex`", lines)
        after = lines[lines.index(MARKDOWN_TITLE) + 1 :]
        self.assertFalse(any(t.startswith("기준:") for t in after[:2]), after[:2])

    def test_a_markdown_document_alone_is_sectioned(self):
        """Like a figure document, a Markdown document served alone still gets its section, so its title says what its
        pins are."""
        pin = line_pin(1, file="/ms/notes/plan.md")
        del pin["page"]
        md = pins_md_text(page([pin], {1: facts(doc_key="nt")}, docs=(NOTES,)))
        self.assertIn(MARKDOWN_TITLE, md.splitlines())

    def test_a_heading_without_the_new_field_is_no_markdown_document(self):
        """renders_in_browser defaults to False: headings built before the field keep their titles."""
        self.assertFalse(MAIN.renders_in_browser)
        md = pins_md_text(page([line_pin(1)], docs=(MAIN,)))
        self.assertNotIn("Markdown", md)


class SkillTeachesMarkdownSuggestions(unittest.TestCase):
    """Both SKILLs say a Markdown line pin carries a suggested edit and count broken Markdown among the obvious errors
    (docs/adr/0024-suggested-edit-obvious-errors.md, ADR-0025 D8), so the two cannot drift apart unnoticed."""

    def test_both_skills_name_markdown_pins_and_the_three_markdown_errors(self):
        """The English and the Korean SKILL each name LaTeX, Markdown and text line pins (ADR-0029 D4) and the table
        cells, the unclosed emphasis or code and the list indentation; neither still says only a LaTeX line pin carries
        one."""
        for path, words, gone in (
            (
                SKILL_MD,
                ("a LaTeX, Markdown or text document carries one", "cell count", "left unclosed", "indented"),
                "Only a LaTeX line pin carries one.",
            ),
            (
                SKILL_KO,
                ("LaTeX·Markdown·텍스트 문서의 줄 핀만 가진다", "칸 수가 다르", "닫히지 않았", "들여쓰기가 틀려"),
                "LaTeX 문서의 줄 핀만 가진다.",
            ),
        ):
            skill = path.read_text(encoding="utf-8")
            for word in words:
                with self.subTest(skill=path.name, word=word):
                    self.assertIn(word, skill)
            self.assertNotIn(gone, skill)

    def test_both_skills_teach_text_pins_and_to_ask_before_a_suggestion_that_adds_hidden_characters(self):
        """Both SKILLs name a text document's section title and its indent range, and tell the agent not to apply a
        suggestion whose block carries pins.md's `숨은 문자:` line before a reply asks (ADR-0029 D7)."""
        for path, words in (
            (
                SKILL_MD,
                ("`— 텍스트(쪽 없음)`", "`indent`", "`숨은 문자:`", "Do not apply it: reply asking", "`line_ends`"),
            ),
            (
                SKILL_KO,
                (
                    "`— 텍스트(쪽 없음)`",
                    "`indent`",
                    "`숨은 문자:`",
                    "넣지 말고, 이름이 적힌 문자마다 필요한지 답글로 묻는다",
                    "`line_ends`",
                ),
            ),
        ):
            skill = path.read_text(encoding="utf-8")
            for word in words:
                with self.subTest(skill=path.name, word=word):
                    self.assertIn(word, skill)


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

    def test_the_markdown_section_and_its_rungs_as_written(self):
        """A block pin and a section pin on notes/plan.md are listed under the Markdown section title with md:table and
        md:section in the range column."""
        block = self.make(doc="nt", file=str(self.md), lo=3, hi=4, scope="block", kind="md:paragraph", note="a")
        section = self.make(doc="nt", file=str(self.md), lo=6, hi=8, scope="section", kind="md:section", note="b")
        text = self.pins_md()
        self.assertIn(MARKDOWN_TITLE, text.splitlines())
        self.assertEqual((row_of(text, block)[3], row_of(text, section)[3]), ("md:paragraph", "md:section"))
        self.assertEqual((self.pin(block)["scope"], self.pin(section)["scope"]), ("block", "section"))

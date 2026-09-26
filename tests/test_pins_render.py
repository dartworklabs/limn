"""limn.pins.render - pins.md from one explicit input, tested directly with records and no server, files or clock.

The whole-server contract (pins.md on disk after a write, GET /pins.md, the guidance lines agents match) is pinned in
test_server.py, test_access.py, test_token_file.py and the version suites; here the renderer is fed PinsMdInput
values and its output checked on its own (coding rule R1).

Run: uv run pytest -q tests/test_pins_render.py
"""
import ast
import copy
import dataclasses
import unittest
from pathlib import Path

from limn.pins import render
from limn.pins.render import DocHeading, PinFacts, PinsMdInput, pins_md_text

RENDER_PY = Path(render.__file__)
T = 1_790_000_000.0
MAIN = DocHeading("main", "본문", "main.tex", False, None, None)
ALICE = {"login": "alice@example.com", "name": "Alice Kim"}
BOB = {"login": "bob@example.com", "name": "Bob Park"}


def facts(**extra):
    """PinFacts of a plain line pin in the first document at main.tex, with nothing decided about it."""
    base = dict(doc_key="main", location="main.tex", line_len=None, badge="", reopened=False, addressed=(), fyi=(),
                round=())
    base.update(extra)
    return PinFacts(**base)


def page(rows, pin_facts=None, **extra):
    """A PinsMdInput over rows: one document, loopback, frozen clock; facts default to facts() for every listed pin."""
    if pin_facts is None:
        pin_facts = {r["id"]: facts() for r in rows if not r.get("done") or r.get("review") is True}
    base = dict(rows=rows, facts=pin_facts, base=None, port=18999, manuscript="/ms", label="원고", repo=None,
                docs=(MAIN,), people={}, now=T, updated="2026-09-26 10:00", token_file=None)
    base.update(extra)
    return PinsMdInput(**base)


def line_pin(pid, **extra):
    """An open line pin at L4-L5 with a note."""
    record = {"id": pid, "file": "/ms/main.tex", "lo": 4, "hi": 5, "page": 1, "note": "note %d" % pid, "kind": "lines"}
    record.update(extra)
    return record


def table_rows(md):
    """The table rows of pins.md (lines starting with '| ' that are not headers)."""
    return [ln for ln in md.splitlines() if ln.startswith("| ") and not ln.startswith("| # |")]


class Purity(unittest.TestCase):
    """The renderer reaches nothing but its input (the import check itself is in test_pins_lifecycle.py)."""

    def test_reads_no_server_global_and_never_imports_the_server(self):
        """No C., DOCS or cur_doc in the module, and no import of limn.server - the input carries all of it."""
        source = RENDER_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertEqual(names & {"C", "DOCS", "cur_doc", "time", "datetime", "os"}, set())
        self.assertNotIn("C.", source)
        modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse({m for m in modules if "server" in m})

    def test_same_input_same_text_and_the_input_is_untouched(self):
        """Rendering is a function of the input: twice gives the same bytes, and no record is mutated."""
        rows = [line_pin(1, author=ALICE), line_pin(2, author=BOB, done=True, review=True, close_reply="done")]
        before = copy.deepcopy(rows)
        p = page(rows)
        self.assertEqual(pins_md_text(p), pins_md_text(p))
        self.assertEqual(rows, before)


class Header(unittest.TestCase):
    """The header block: counts, the manuscript and paper lines, and the guidance lines' base URL."""

    def test_empty_single_document_keeps_the_old_shape(self):
        """No pins: no document subsections, one '열린 핀 없음' table row, loopback URLs from the port."""
        md = pins_md_text(page([]))
        self.assertTrue(md.startswith("# 수정 요청 핀\n\n원고: `/ms`\n논문: 원고 · 저장소: (없음)\n"))
        self.assertIn("갱신: 2026-09-26 10:00  ·  열린 핀 0건  ·  닫힌 핀 0건", md)
        self.assertIn("http://127.0.0.1:18999/api/pins/N/close", md)
        self.assertNotIn("\n## ", md)
        self.assertTrue(md.endswith("| — | — | 열린 핀 없음 | | |\n"))

    def test_counts_open_review_and_done(self):
        """Open, awaiting-review and done pins are counted apart; only open ones are rows of the open table."""
        rows = [line_pin(1), line_pin(2, done=True, review=True), line_pin(3, done=True)]
        md = pins_md_text(page(rows))
        self.assertIn("열린 핀 1건  ·  검토 대기 1건(맨 아래, 처리하지 않는다)  ·  닫힌 핀 1건", md)
        self.assertIn("## 검토 대기 1건", md)

    def test_build_stamp_line_only_with_a_git_head_and_a_time(self):
        """'기준:' appears for a real head with a build time; '-' (outside git) or a missing stamp omits it."""
        stamped = dataclasses.replace(MAIN, head="abc1234", built_at="2026-09-26 09:59")
        self.assertIn("기준: abc1234 · 빌드 2026-09-26 09:59\n", pins_md_text(page([], docs=(stamped,))))
        for head, built in (("-", "2026-09-26 09:59"), ("abc1234", None), (None, None)):
            doc = dataclasses.replace(MAIN, head=head, built_at=built)
            self.assertNotIn("기준:", pins_md_text(page([], docs=(doc,))))

    def test_repo_adds_the_origin_check(self):
        """A repository URL is named and the guidance asks to compare the checkout's origin."""
        md = pins_md_text(page([], repo="https://github.com/example/paper"))
        self.assertIn("저장소: https://github.com/example/paper", md)
        self.assertIn("git remote get-url origin", md)


class TokenLine(unittest.TestCase):
    """The agent-auth line: the token-file clause only for a local reader of a file that exists."""

    def test_loopback_reader_gets_the_file_clause(self):
        """base None (the file on disk) with a token file: the clause with the curl form follows TOKEN_GUIDANCE."""
        md = pins_md_text(page([], token_file="~/.config/limn/p.token"))
        line = next(ln for ln in md.splitlines() if ln.startswith(render.TOKEN_GUIDANCE))
        self.assertEqual(line, render.token_guidance_line("~/.config/limn/p.token"))
        self.assertIn("$(cat ~/.config/limn/p.token)", line)

    def test_remote_reader_gets_no_file_clause_and_a_remote_line(self):
        """A remote base leaves the clause out (it cannot reach this machine's file) and adds the remote curl."""
        md = pins_md_text(page([], token_file="~/.config/limn/p.token", base="https://paper.example.ts.net"))
        self.assertEqual(md.splitlines().count(render.TOKEN_GUIDANCE), 1)
        self.assertIn(" · 원격: `curl -s https://paper.example.ts.net/pins.md`", md)

    def test_loopback_base_is_not_remote(self):
        """GET /pins.md from loopback passes the loopback base: still local, no remote line."""
        md = pins_md_text(page([], token_file="~/t.token", base="http://127.0.0.1:18999"))
        self.assertNotIn("원격:", md)
        self.assertIn("$(cat ~/t.token)", md)


class OpenRows(unittest.TestCase):
    """The number column's markers and the note column, each from the record or its facts."""

    def test_markers_in_priority_order(self):
        """reopened > handed to a person > FYI > question > overlap > claim > edited > stale, names from people."""
        r = line_pin(7, kind_req="question", edited_at="t", stale=True, claimed_by={"name": "Kim"}, claim_until=T + 60,
                     eta_ts=T + 14 * 60)
        f = facts(reopened=True, addressed=("bob@example.com",), fyi=("carol@example.com",), badge="#3 범위 안")
        md = pins_md_text(page([r], {7: f}, people={"bob@example.com": BOB}))
        self.assertEqual(table_rows(md)[0].split(" | ")[0],
                         "| 7 · 다시 열림 · → @Bob Park · 참고 @carol@example.com · 질문 · #3 범위 안 · "
                         "처리 중(Kim, 약 15분) · 수정됨 · 위치 잃음")
        self.assertIn("핀 1건은 담당이 사람인 핀이다", md)
        self.assertIn(render.LEGEND, md)

    def test_claim_is_measured_against_the_input_clock(self):
        """An expired claim (claim_until <= now) shows no marker; a passed estimate shows '예상 초과'."""
        r = line_pin(1, claimed_by={"name": "Kim"}, claim_until=T + 60, eta_ts=T + 30)
        self.assertIn("처리 중(Kim, 약 5분)", pins_md_text(page([r])))
        self.assertIn("처리 중(Kim, 예상 초과)", pins_md_text(page([r], now=T + 31)))
        self.assertNotIn("처리 중", pins_md_text(page([r], now=T + 60)).split("표시:")[0].split("| # |")[-1])

    def test_note_cells_escape_pipes_and_newlines(self):
        """The note keeps its lines as ⏎ and a pipe cannot add a column."""
        row = table_rows(pins_md_text(page([line_pin(1, note="a | b\r\nc")])))[0]
        self.assertTrue(row.endswith("| a \\| b ⏎ c |"))
        self.assertEqual(row.count(" | "), 4)

    def test_author_prefix_only_with_two_or_more_authors(self):
        """'[name]' leads the note once pins come from 2+ authors; a single author gets none."""
        one = pins_md_text(page([line_pin(1, author=ALICE), line_pin(2, author=ALICE)]))
        two = pins_md_text(page([line_pin(1, author=ALICE), line_pin(2, author=BOB)]))
        self.assertNotIn("[Alice Kim]", one)
        self.assertIn("[Alice Kim] note 1", two)
        self.assertIn("[Bob Park] note 2", two)

    def test_location_column_uses_the_facts_location(self):
        """The file shown is facts.location, not the stored absolute path."""
        row = table_rows(pins_md_text(page([line_pin(1)], {1: facts(location="sec/intro.tex")})))[0]
        self.assertIn("| `sec/intro.tex L4-L5` |", row)

    def test_thread_shows_the_last_three_of_the_round(self):
        """Five posts in the round: '[스레드 5건, 앞 2건은 GET /api/pins/N]' and the last three, reopen labelled."""
        posts = tuple({"by": {"name": "P%d" % i}, "text": "t%d" % i} for i in range(4))
        posts += ({"by": {"name": "Q"}, "text": "why", "ev": "reopen"}, {"by": {"name": "Q"}, "ev": "close"})
        row = table_rows(pins_md_text(page([line_pin(9, note="")], {9: facts(round=posts)})))[0]
        self.assertTrue(row.endswith("| [스레드 5건, 앞 2건은 GET /api/pins/9] P2: t2 ⏎ P3: t3 ⏎ 다시 연 이유(Q): why |"))


class LongLineQuote(unittest.TestCase):
    """The «quote» exception of a line pin depends on the facts' line length and the record's scope."""

    def quote_shown(self, line_len, **extra):
        """Whether pins.md shows the quote of a one-line pin whose line is line_len characters long."""
        r = line_pin(1, lo=3, hi=3, quote="q|x", **extra)
        return "«q\\|x» " in pins_md_text(page([r], {1: facts(line_len=line_len)}))

    def test_only_a_line_over_600_characters(self):
        """600 is not enough, 601 is; an unknown length (file outside the tree) never shows it."""
        self.assertFalse(self.quote_shown(600))
        self.assertTrue(self.quote_shown(601))
        self.assertFalse(self.quote_shown(None))

    def test_only_raw_para_or_no_scope(self):
        """An env or lines scope never shows the quote, however long the line."""
        self.assertTrue(self.quote_shown(700, scope="para"))
        self.assertFalse(self.quote_shown(700, scope="env"))
        self.assertFalse(self.quote_shown(700, scope="lines"))

    def test_region_pin_always_shows_its_quote(self):
        """A view-only PDF's pin shows its quote and region text, with no line and '영역' as range."""
        r = {"id": 1, "file": None, "pdf": "/ms/review.pdf", "page": 2, "frac": [0.1, 0.2, 0.5, 0.1], "note": "n",
             "quote": "Reviewer one"}
        md = pins_md_text(page([r], {1: facts(location="")}))
        self.assertIn("| 1 | 2 | 쪽 2, 영역 가로 10–60% 세로 20–30% | 영역 | «Reviewer one» n |", md)
        self.assertIn("보기 전용 PDF 의 핀은 줄 번호가 없다", md)


class Documents(unittest.TestCase):
    """Several documents, or a pin under a key not configured, group the rows into subsections."""

    def test_multi_document_sections_in_configured_order(self):
        """Each document with open pins gets '## name · key · path'; a view-only one says so; empty ones are skipped."""
        rr = DocHeading("rr", "답변서", "rr/rr.tex", False, None, None)
        rv = DocHeading("rv", "리뷰", "review.pdf", True, "bbb2222", "2026-09-25 08:00")
        region = {"id": 2, "file": None, "pdf": "/ms/review.pdf", "page": 1, "frac": [0, 0, 1, 1], "note": "r"}
        rows = [line_pin(1), region]
        md = pins_md_text(page(rows, {1: facts(doc_key="rr"), 2: facts(doc_key="rv", location="")},
                               docs=(MAIN, rr, rv)))
        self.assertIn("문서: 본문(`main`) 0건 · 답변서(`rr`) 1건 · 리뷰(`rv`, 보기 전용) 1건", md)
        self.assertNotIn("## 본문", md)
        self.assertLess(md.index("## 답변서 · `rr` · `rr/rr.tex`"),
                        md.index("## 리뷰 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)\n기준: bbb2222 · 그림 2026-09-25 08:00"))

    def test_unknown_document_key_is_its_own_section_even_with_one_document(self):
        """A pin under a key not in the configuration sections the sheet and asks to check with the user."""
        md = pins_md_text(page([line_pin(1)], {1: facts(doc_key="gone")}))
        self.assertIn("## 설정에 없는 문서 · `gone` — 이 뷰어의 --doc 목록에 없다", md)
        self.assertIn("설정에 없는 문서(`gone`) 1건", md)

    def test_multi_document_without_open_pins(self):
        """Sectioned but nothing open: one '열린 핀 없음' line instead of tables."""
        rr = DocHeading("rr", "답변서", "rr/rr.tex", False, None, None)
        self.assertTrue(pins_md_text(page([], docs=(MAIN, rr))).endswith("\n\n열린 핀 없음\n"))


class ReviewTable(unittest.TestCase):
    """The awaiting-review subsection: sorted by id, the confirmer, the close answer, the doc key when sectioned."""

    def test_rows_sorted_with_author_and_answer(self):
        """Rows by id; the author confirms; a close with no reply says so; ref follows the reply."""
        rows = [line_pin(5, done=True, review=True, author=BOB, close_reply="  fixed\n it ", close_ref="PR #3"),
                line_pin(2, done=True, review=True, kind_req="question")]
        md = pins_md_text(page(rows))
        tail = md.split("| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |\n|---|---|---|---|\n")[1]
        self.assertEqual(tail, "| 2 · 질문 | `main.tex L4-L5` | 작성자 기록 없음 | (설명 없이 닫힘) |\n"
                               "| 5 | `main.tex L4-L5` | Bob Park | fixed it (PR #3) |\n")

    def test_sectioned_rows_name_the_document(self):
        """With subsections (two documents), the location starts with the document key; one document never does -
        the review rows alone do not section the sheet."""
        rows = [line_pin(1, done=True, review=True)]
        rr = DocHeading("rr", "답변서", "rr/rr.tex", False, None, None)
        md = pins_md_text(page(rows, {1: facts(doc_key="rr")}, docs=(MAIN, rr)))
        self.assertIn("| 1 | `rr` · `main.tex L4-L5` |", md)
        self.assertIn("| 1 | `main.tex L4-L5` |", pins_md_text(page(rows, {1: facts(doc_key="gone")})))


class Helpers(unittest.TestCase):
    """The small pure pieces the text is built from."""

    def test_flat_collapses_whitespace_and_truncates(self):
        """Runs of whitespace become one space; over n characters ends with an ellipsis within n."""
        self.assertEqual(render.flat(" a\n\tb  c ", 10), "a b c")
        self.assertEqual(render.flat("abcdefghij", 5), "abcd…")
        self.assertEqual(render.flat(None, 5), "")

    def test_region_text_tolerates_a_malformed_frac(self):
        """A frac that is not four numbers reads as zeros instead of failing the whole sheet."""
        self.assertEqual(render.region_text_of({"page": 2, "frac": ["x", 0, 0, 0]}), "쪽 2, 영역 가로 0–0% 세로 0–0%")
        self.assertEqual(render.region_text_of({}), "쪽 ?, 영역 가로 0–0% 세로 0–0%")


if __name__ == "__main__":
    unittest.main()

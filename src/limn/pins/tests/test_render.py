"""limn.pins.listing.render - pins.md from one explicit input, tested directly with records and no server, files or clock.

The whole-server contract (pins.md on disk after a write, GET /pins.md, the guidance lines agents match) is pinned
through server.py at the end of this file (PinsMdV2 to PinsMdInstructions: claims, badges, questions, review,
people addressed, the agents' instructions), and in test_server.py, test_access.py, test_token_file.py and the
feature files. The classes above feed the renderer PinsMdInput values and check its output on its own (coding rule
R1).

Run: uv run pytest -q src/limn/pins/tests/test_render.py
"""

import ast
import copy
import dataclasses
import json
import re
import shutil
import unittest
from pathlib import Path

from limn.builds import figure_map as figmap
from limn.pins.claims import input as claims_input
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.listing import render, render as md_render
from limn.pins.listing.render import DocHeading, PinFacts, PinsMdInput, pins_md_text
from limn.pins.location import mapping
from limn.pins.model import ThreadEntry
from limn.security.access import LOCAL_ACTOR

from helpers import (
    SKILL_KO,
    SKILL_MD,
    Base,
    add_pin,
    edit_pin,
    extract_js_fn,
    ps,
    records,
    req,
    run_node,
    set_config,
    write_records,
)
from helpers_access import ALICE_ACTOR, BOB_ACTOR, TS_HOST, AccessBase, token_create
from helpers_authority import post_authority

RENDER_PY = Path(render.__file__)
T = 1_790_000_000.0
MAIN = DocHeading("main", "본문", "main.tex", view_only=False, builds_from_source=True, head=None, built_at=None)


def facts(**extra):
    """PinFacts of a plain line pin in the first document at main.tex, with nothing decided about it."""
    base = dict(
        doc_key="main", location="main.tex", line_len=None, badge="", reopened=False, addressed=(), fyi=(), round=()
    )
    base.update(extra)
    return PinFacts(**base)


def page(rows, pin_facts=None, **extra):
    """A PinsMdInput over rows: one document, loopback, frozen clock; facts default to facts() for every listed pin."""
    if pin_facts is None:
        pin_facts = {r["id"]: facts() for r in rows if not r.get("done") or r.get("review") is True}
    base = dict(
        rows=rows,
        facts=pin_facts,
        base=None,
        port=18999,
        manuscript="/ms",
        label="원고",
        repo=None,
        docs=(MAIN,),
        people={},
        now=T,
        updated="2026-09-26 10:00",
        token_file=None,
    )
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
        rows = [
            line_pin(1, author=ALICE_ACTOR),
            line_pin(2, author=BOB_ACTOR, done=True, review=True, close_reply="done"),
        ]
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
        r = line_pin(
            7,
            kind_req="question",
            edited_at="t",
            stale=True,
            claimed_by={"name": "Kim"},
            claim_until=T + 60,
            eta_ts=T + 14 * 60,
        )
        f = facts(reopened=True, addressed=("bob@example.com",), fyi=("carol@example.com",), badge="#3 범위 안")
        md = pins_md_text(page([r], {7: f}, people={"bob@example.com": BOB_ACTOR}))
        self.assertEqual(
            table_rows(md)[0].split(" | ")[0],
            "| 7 · 다시 열림 · → @Bob Park · 참고 @carol@example.com · 질문 · #3 범위 안 · "
            "처리 중(Kim, 약 15분) · 수정됨 · 위치 잃음",
        )
        self.assertIn("핀 1건은 담당이 사람인 핀이다", md)
        self.assertIn(render.LEGEND, md)

    def test_claim_is_measured_against_the_input_clock(self):
        """An expired claim (claim_until <= now) shows no marker; a passed estimate shows '예상 초과'."""
        r = line_pin(1, claimed_by={"name": "Kim"}, claim_until=T + 60, eta_ts=T + 30)
        self.assertIn("처리 중(Kim, 약 5분)", pins_md_text(page([r])))
        self.assertIn("처리 중(Kim, 예상 초과)", pins_md_text(page([r], now=T + 31)))
        self.assertNotIn("처리 중", pins_md_text(page([r], now=T + 60)).split("표시:")[0].split("| # |")[-1])

    def test_a_claim_until_without_claimed_by_still_shows_the_marker(self):
        """Pinned on purpose: a hand-edited open pin with a live claim_until but no claimed_by object shows
        '처리 중(?)' - pins.md reads the record (lifecycle.claim_holds), not the lifted Claim that POST /claim decides
        on. Changing this changes the agent contract and must be deliberate."""
        r = line_pin(1, claim_until=T + 60)
        self.assertEqual(table_rows(pins_md_text(page([r])))[0].split(" | ")[0], "| 1 · 처리 중(?)")

    def test_note_cells_escape_pipes_and_newlines(self):
        """The note keeps its lines as ⏎ and a pipe cannot add a column."""
        row = table_rows(pins_md_text(page([line_pin(1, note="a | b\r\nc")])))[0]
        self.assertTrue(row.endswith("| a \\| b ⏎ c |"))
        self.assertEqual(row.count(" | "), 4)

    def test_author_prefix_only_with_two_or_more_authors(self):
        """'[name]' leads the note once pins come from 2+ authors; a single author gets none."""
        one = pins_md_text(page([line_pin(1, author=ALICE_ACTOR), line_pin(2, author=ALICE_ACTOR)]))
        two = pins_md_text(page([line_pin(1, author=ALICE_ACTOR), line_pin(2, author=BOB_ACTOR)]))
        self.assertNotIn("[Alice Kim]", one)
        self.assertIn("[Alice Kim] note 1", two)
        self.assertIn("[Bob Park] note 2", two)

    def test_location_column_uses_the_facts_location(self):
        """The file shown is facts.location, not the stored absolute path."""
        row = table_rows(pins_md_text(page([line_pin(1)], {1: facts(location="sec/intro.tex")})))[0]
        self.assertIn("| `sec/intro.tex L4-L5` |", row)

    def test_thread_shows_the_last_three_of_the_round(self):
        """Five posts in the round: '[스레드 5건, 앞 2건은 GET /api/pins/N]' and the last three, reopen labelled."""
        posts = [{"by": {"name": "P%d" % i}, "text": "t%d" % i} for i in range(4)]
        posts += [{"by": {"name": "Q"}, "text": "why", "ev": "reopen"}, {"by": {"name": "Q"}, "ev": "close"}]
        posts = tuple(ThreadEntry.from_record(p) for p in posts)
        row = table_rows(pins_md_text(page([line_pin(9, note="")], {9: facts(round=posts)})))[0]
        self.assertTrue(
            row.endswith("| [스레드 5건, 앞 2건은 GET /api/pins/9] P2: t2 ⏎ P3: t3 ⏎ 다시 연 이유(Q): why |")
        )


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
        r = {
            "id": 1,
            "file": None,
            "pdf": "/ms/review.pdf",
            "page": 2,
            "frac": [0.1, 0.2, 0.5, 0.1],
            "note": "n",
            "quote": "Reviewer one",
        }
        md = pins_md_text(page([r], {1: facts(location="")}))
        self.assertIn("| 1 | 2 | 쪽 2, 영역 가로 10–60% 세로 20–30% | 영역 | «Reviewer one» n |", md)
        self.assertIn("보기 전용 PDF 의 핀은 줄 번호가 없다", md)


class DocumentSections(unittest.TestCase):
    """Several documents, or a pin under a key not configured, group the rows into subsections."""

    def test_multi_document_sections_in_configured_order(self):
        """Each document with open pins gets '## name · key · path'; a view-only one says so; empty ones are skipped."""
        rr = DocHeading("rr", "답변서", "rr/rr.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
        rv = DocHeading(
            "rv",
            "리뷰",
            "review.pdf",
            view_only=True,
            builds_from_source=False,
            head="bbb2222",
            built_at="2026-09-25 08:00",
        )
        region = {"id": 2, "file": None, "pdf": "/ms/review.pdf", "page": 1, "frac": [0, 0, 1, 1], "note": "r"}
        rows = [line_pin(1), region]
        md = pins_md_text(
            page(rows, {1: facts(doc_key="rr"), 2: facts(doc_key="rv", location="")}, docs=(MAIN, rr, rv))
        )
        self.assertIn("문서: 본문(`main`) 0건 · 답변서(`rr`) 1건 · 리뷰(`rv`, 보기 전용) 1건", md)
        self.assertNotIn("## 본문", md)
        self.assertLess(
            md.index("## 답변서 · `rr` · `rr/rr.tex`"),
            md.index(
                "## 리뷰 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)\n기준: bbb2222 · 그림 2026-09-25 08:00"
            ),
        )

    def test_stamp_word_follows_builds_from_source_and_label_follows_view_only(self):
        """The heading's two decisions read two capabilities: a document with line pins whose pages are read in, not
        built, gets the '그림' stamp and no view-only label anywhere."""
        fg = DocHeading(
            "fg",
            "도표",
            "fig/figs.pdf",
            view_only=False,
            builds_from_source=False,
            head="ccc3333",
            built_at="2026-09-25 09:00",
        )
        md = pins_md_text(page([line_pin(1)], {1: facts(doc_key="fg", location="fig/make.py")}, docs=(MAIN, fg)))
        self.assertIn("## 도표 · `fg` · `fig/figs.pdf`\n기준: ccc3333 · 그림 2026-09-25 09:00", md)
        self.assertIn("문서: 본문(`main`) 0건 · 도표(`fg`) 1건", md)
        self.assertNotIn("보기 전용", md)

    def test_unknown_document_key_is_its_own_section_even_with_one_document(self):
        """A pin under a key not in the configuration sections the sheet and asks to check with the user."""
        md = pins_md_text(page([line_pin(1)], {1: facts(doc_key="gone")}))
        self.assertIn("## 설정에 없는 문서 · `gone` — 이 뷰어의 --doc 목록에 없다", md)
        self.assertIn("설정에 없는 문서(`gone`) 1건", md)

    def test_multi_document_without_open_pins(self):
        """Sectioned but nothing open: one '열린 핀 없음' line instead of tables."""
        rr = DocHeading("rr", "답변서", "rr/rr.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
        self.assertTrue(pins_md_text(page([], docs=(MAIN, rr))).endswith("\n\n열린 핀 없음\n"))


class ReviewTable(unittest.TestCase):
    """The awaiting-review subsection: sorted by id, the confirmer, the close answer, the doc key when sectioned."""

    def test_rows_sorted_with_author_and_answer(self):
        """Rows by id; the author confirms; a close with no reply says so; ref follows the reply."""
        rows = [
            line_pin(5, done=True, review=True, author=BOB_ACTOR, close_reply="  fixed\n it ", close_ref="PR #3"),
            line_pin(2, done=True, review=True, kind_req="question"),
        ]
        md = pins_md_text(page(rows))
        tail = md.split("| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |\n|---|---|---|---|\n")[1]
        self.assertEqual(
            tail,
            "| 2 · 질문 | `main.tex L4-L5` | 작성자 기록 없음 | (설명 없이 닫힘) |\n"
            "| 5 | `main.tex L4-L5` | Bob Park | fixed it (PR #3) |\n",
        )

    def test_sectioned_rows_name_the_document(self):
        """With subsections (two documents), the location starts with the document key; one document never does -
        the review rows alone do not section the sheet."""
        rows = [line_pin(1, done=True, review=True)]
        rr = DocHeading("rr", "답변서", "rr/rr.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
        md = pins_md_text(page(rows, {1: facts(doc_key="rr")}, docs=(MAIN, rr)))
        self.assertIn("| 1 | `rr` · `main.tex L4-L5` |", md)
        self.assertIn("| 1 | `main.tex L4-L5` |", pins_md_text(page(rows, {1: facts(doc_key="gone")})))


class RenderHelpers(unittest.TestCase):
    """The small pure pieces the text is built from."""

    def test_flat_collapses_whitespace_and_truncates(self):
        """Runs of whitespace become one space; over n characters ends with an ellipsis within n."""
        self.assertEqual(mapping.flat(" a\n\tb  c ", 10), "a b c")
        self.assertEqual(mapping.flat("abcdefghij", 5), "abcd…")
        self.assertEqual(mapping.flat(None, 5), "")

    def test_region_text_tolerates_a_malformed_frac(self):
        """A frac that is not four numbers reads as zeros instead of failing the whole sheet."""
        self.assertEqual(render.region_text_of({"page": 2, "frac": ["x", 0, 0, 0]}), "쪽 2, 영역 가로 0–0% 세로 0–0%")
        self.assertEqual(render.region_text_of({}), "쪽 ?, 영역 가로 0–0% 세로 0–0%")

    def test_region_text_reads_a_non_finite_frac_as_zeros_and_never_raises(self):
        """NaN, an infinity and an integer no float holds (shapes the store keeps in a hand-edited frac) read as the
        zero box, like any other malformed frac; a finite frac keeps its text."""
        zero = "쪽 2, 영역 가로 0–0% 세로 0–0%"
        for bad in (float("nan"), float("inf"), -float("inf"), 10**400):
            with self.subTest(bad=bad):
                self.assertEqual(render.region_text_of({"page": 2, "frac": [bad, 0.1, 0.2, 0.3]}), zero)
        self.assertEqual(
            render.region_text_of({"page": 2, "frac": [0.0, 0.0, 1.0, 1.0]}), "쪽 2, 영역 가로 0–100% 세로 0–100%"
        )


class BadgeWords(unittest.TestCase):
    """The overlap badges read as words ('#20 범위 안', '#20과 같은 범위', '#20과 일부 겹침') with the particle the
    number takes when read in Korean, and both skill procedures quote the pins.md markers verbatim."""

    NUMS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 19, 20, 100, 1000, 21, 32]

    def test_josa_follows_korean_reading(self):
        got = [md_render.josa(n, "과", "와") for n in self.NUMS]
        self.assertEqual(
            got,
            [
                "과",
                "와",
                "과",
                "와",
                "와",
                "과",
                "과",
                "과",
                "와",
                "과",
                "과",
                "와",
                "와",
                "와",
                "과",
                "과",
                "과",
                "과",
                "와",
            ],
        )
        if shutil.which("node"):
            js = extract_js_fn("josa") + "\nconsole.log(JSON.stringify(%s.map(n=>josa(n,'과','와'))));" % json.dumps(
                self.NUMS
            )
            self.assertEqual(json.loads(run_node(js)), got)

    def test_rel_badge_prefers_same_range_then_inside_then_partial(self):
        by_id = {1: {"lo": 4, "hi": 9}, 2: {"lo": 4, "hi": 9}, 3: {"lo": 5, "hi": 6}, 20: {"lo": 8, "hi": 12}}
        self.assertEqual(
            md_render.rel_badge([{"id": 1, "rel": "contains"}], by_id, {"id": 2, "lo": 4, "hi": 9}), "#1과 같은 범위"
        )
        self.assertEqual(
            md_render.rel_badge([{"id": 2, "rel": "inside"}], by_id, {"id": 1, "lo": 4, "hi": 9}), "#2와 같은 범위"
        )
        self.assertEqual(
            md_render.rel_badge(
                [{"id": 1, "rel": "inside"}, {"id": 2, "rel": "inside"}], by_id, {"id": 3, "lo": 5, "hi": 6}
            ),
            "#1 범위 안",
        )
        self.assertEqual(
            md_render.rel_badge([{"id": 20, "rel": "partial"}], by_id, {"id": 3, "lo": 5, "hi": 9}), "#20과 일부 겹침"
        )
        self.assertEqual(
            md_render.rel_badge([{"id": 2, "rel": "partial"}], by_id, {"id": 9, "lo": 8, "hi": 12}), "#2와 일부 겹침"
        )
        self.assertEqual(md_render.rel_badge([{"id": 3, "rel": "contains"}], by_id, {"id": 1, "lo": 4, "hi": 9}), "")

    def test_skill_symbol_table_uses_words(self):
        # pins.md markers are a language-stable contract: both procedures quote them verbatim.
        for path, head, end in (
            (SKILL_MD, "### Markers in the number column", "### Rules"),
            (SKILL_KO, "### 번호 칸의 표시", "### 규칙"),
        ):
            skill = path.read_text(encoding="utf-8")
            table = skill[skill.index(head) : skill.index(end)]
            for row in (
                "| `#N 범위 안` |",
                "| `#N과 같은 범위` |",
                "| `#N과 일부 겹침` |",
                "| `처리 중(<이름>, 약 N분)` |",
                "| `수정됨` |",
                "| `위치 잃음` |",
            ):
                self.assertIn(row, table)
            self.assertNotRegex(
                table,
                r"^\| `[⊂∩⏳✎⚠]",
            )

    def test_skill_teaches_figure_pins_and_rebuilds_only_latex(self):
        """Both SKILLs carry the 요소 잃음 marker row, the figure pin rule tied to the section title — 그림(요소 지도),
        the three origins of a figure region pin, and a rebuild rule keyed on kind "tex" (not the old view-only
        line)."""
        for path, head, end, words in (
            (
                SKILL_MD,
                "### Markers in the number column",
                "### Rules",
                (
                    'kind` in `GET /api/docs` is `"tex"`',
                    "figure repository",
                    "— 그림(요소 지도)",
                    "design file",
                    "could not be read",
                ),
            ),
            (
                SKILL_KO,
                "### 번호 칸의 표시",
                "### 규칙",
                ('`kind` 가 `"tex"`', "그림 저장소", "— 그림(요소 지도)", "디자인 파일", "읽지 못"),
            ),
        ):
            skill = path.read_text(encoding="utf-8")
            self.assertIn("| `요소 잃음` |", skill[skill.index(head) : skill.index(end)])
            for w in words:
                self.assertIn(w, skill)
            self.assertNotIn("View-only documents have no rebuild.", skill)
            self.assertNotIn("보기 전용 문서는 재빌드가 없다.", skill)

    def test_skill_ko_shares_its_figure_literals_with_the_pins_md_guidance(self):
        """The Korean words pins.md's FIGURE_GUIDANCE teaches (the shared part, the lost marker, the figure repository,
        asking a person, not closing when the place cannot be found: 닫지 말고, and reporting instead of editing an element
        from a design tool) also stand in SKILL.ko.md, so the two cannot drift into contradiction unnoticed - a flip
        from "do not close" to "close" would drop the literal."""
        skill = SKILL_KO.read_text(encoding="utf-8")
        for literal in (
            "공통 부품",
            "요소 잃음",
            "그림 저장소",
            "사람에게 묻",
            "닫지 말고",
            "디자인 도구에서 왔으면 고치지 말고 보고한다",
        ):
            with self.subTest(literal=literal):
                self.assertIn(literal, render.FIGURE_GUIDANCE)
                self.assertIn(literal, skill)


EL7 = {
    "id": "B2/calendar/m07",
    "path": ["B2", "B2/calendar", "B2/calendar/m07"],
    "label": "7월",
    "part": "MonthCell",
    "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
    "frac": [0.47, 0.18, 0.07, 0.12],
}
FIG = DocHeading(
    "fig", "그림", "figs/out/figures.limnmap.json", view_only=False, builds_from_source=False, head=None, built_at=None,
    has_element_map=True,
)  # fmt: skip
PDF = DocHeading("rv", "리뷰", "review.pdf", view_only=True, builds_from_source=False, head=None, built_at=None)
VIEW_ONLY_CLAUSE = "보기 전용 PDF 의 핀은 줄 번호가 없다"


def guidance_line(md):
    """The close-guidance paragraph of pins.md."""
    return next(line for line in md.splitlines() if line.startswith("처리한 핀은 닫는다"))


def el_with_impl(file, lo=410, hi=470):
    """EL7 with its shared part at file, lo..hi."""
    return dict(EL7, impl={"file": file, "lo": lo, "hi": hi})


def region_pin(pid, doc_pdf="/ms/figs/out/figures.pdf", **extra):
    """An open region pin on page 1 with a note - the shape of a pin on a view-only PDF or of a figure pick that fell
    back to a region."""
    r = {
        "id": pid,
        "pdf": doc_pdf,
        "page": 1,
        "frac": [0.55, 0.18, 0.07, 0.12],
        "kind": "region",
        "note": "note %d" % pid,
    }
    r.update(extra)
    return r


class FigureRows(unittest.TestCase):
    """A figure pin's pins.md row: lines and kind as any line pin, the element's «label», its shared part and a lost
    element, and one guidance clause while figure pins are open."""

    def test_a_figure_pin_row_shows_its_lines_kind_label_and_shared_part(self):
        """Location and range as the record says; «7월» before the note; the shared part after it,
        manuscript-relative."""
        r = line_pin(
            1,
            file="/ms/figs/src/B2_calendar.py",
            lo=88,
            hi=95,
            scope="el",
            kind="el:MonthCell",
            el=EL7,
            note="글자를 키워 줘",
        )
        md = pins_md_text(page([r], {1: facts(location="figs/src/B2_calendar.py", impl_scope="figs")}))
        self.assertIn(
            "| 1 | 1 | `figs/src/B2_calendar.py L88-L95` | el:MonthCell | «7월» 글자를 키워 줘 ⏎ 공통 부품: figs/lib/components.py:410-470 |",
            md,
        )

    def test_a_lost_element_is_marked_like_a_lost_location(self):
        """el_sync lost: 요소 잃음 in the number cell."""
        md = pins_md_text(page([line_pin(1, scope="el", kind="el:MonthCell", el=EL7)], {1: facts(el_sync="lost")}))
        self.assertIn("| 1 · 요소 잃음 |", md)

    def test_an_element_that_is_ok_or_moved_or_unknown_is_not_marked_lost(self):
        """Only lost is a warning: ok, moved and no answer (the map did not load) leave the number cell as it was."""
        for sync in ("ok", "moved", None):
            with self.subTest(el_sync=sync):
                md = pins_md_text(page([line_pin(1, el=EL7)], {1: facts(el_sync=sync)}))
                self.assertNotIn("요소 잃음", md.replace(render.FIGURE_GUIDANCE, ""))
                self.assertIn("| 1 |", md)

    def test_a_lost_element_and_a_lost_location_are_both_named_in_the_row_order(self):
        """The two warnings sit side by side in the number cell, the location's first (the stale rule is unchanged)."""
        md = pins_md_text(page([line_pin(1, el=EL7, stale=True)], {1: facts(el_sync="lost")}))
        self.assertIn("| 1 · 위치 잃음 · 요소 잃음 |", md)

    def test_the_figure_clause_needs_an_element_pin(self):
        """Without an element pin the guidance is as before; with one it gains exactly FIGURE_GUIDANCE."""
        plain = guidance_line(pins_md_text(page([line_pin(1)])))
        self.assertNotIn(render.FIGURE_GUIDANCE, plain)
        self.assertEqual(guidance_line(pins_md_text(page([line_pin(1, el=EL7)]))), plain + render.FIGURE_GUIDANCE)

    def test_a_region_pin_with_an_element_takes_the_figure_clause_not_the_view_only_one(self):
        """An element drawn without code is a region pin: «label» before the note, the figure clause, no view-only
        one."""
        r = region_pin(
            1,
            quote="8월",
            note="색",
            el={"id": "B2/calendar/m08", "path": ["B2", "B2/calendar", "B2/calendar/m08"], "label": "8월"},
        )
        md = pins_md_text(page([r]))
        self.assertIn("| 영역 | «8월» 색 |", md)
        self.assertIn(render.FIGURE_GUIDANCE, md)
        self.assertNotIn(VIEW_ONLY_CLAUSE, md)

    def test_an_element_without_a_label_keeps_the_usual_quote_rule(self):
        """No label: the long-line quote rule applies as to any line pin."""
        r = line_pin(1, lo=4, hi=4, quote="q", el={"id": "B2", "path": ["B2"]})
        self.assertIn("«q» note 1", pins_md_text(page([r], {1: facts(line_len=700)})))

    def test_a_label_with_a_pipe_or_a_newline_cannot_break_the_row(self):
        """The «label» goes through md_cell: a pipe is escaped and a newline becomes a space, so the row keeps its 5
        columns."""
        el = dict(EL7, label="a|b\nc")
        md = pins_md_text(page([line_pin(1, el=el)]))
        row = next(line for line in md.splitlines() if line.startswith("| 1 |"))
        self.assertIn("«a\\|b c» note 1", row)
        self.assertEqual(len(re.split(r"(?<!\\)\|", row)), 5 + 2)

    def test_an_element_with_a_label_takes_precedence_over_a_stored_quote_on_a_long_line(self):
        """A figure pin's «label» is always shown and replaces the long-line quote: never two «…» before one note."""
        r = line_pin(1, lo=4, hi=4, quote="the quote", el=EL7)
        row = next(
            line for line in pins_md_text(page([r], {1: facts(line_len=900)})).splitlines() if line.startswith("| 1 |")
        )
        self.assertIn("«7월» note 1", row)
        self.assertNotIn("the quote", row)

    def test_a_figure_label_alone_does_not_bring_the_legend(self):
        """The legend explains «…» as rendered text; a figure's «label» does not switch it on (FIGURE_GUIDANCE explains
        it)."""
        self.assertNotIn(render.LEGEND, pins_md_text(page([line_pin(1, el=EL7)])))

    def test_a_malformed_el_is_no_figure_pin_and_never_raises(self):
        """A stored el that is not a shape the store trusts (a number, a list, a path that is not strings) is ignored:
        no «label», no clause, no part - the row and the guidance are the plain line pin's."""
        plain = pins_md_text(page([line_pin(1)]))
        for bad in (
            5,
            [],
            "x",
            {"id": "", "path": []},
            {"id": "a", "path": [1]},
            {"id": "a", "path": ["a"], "label": 3},
        ):
            with self.subTest(el=bad):
                self.assertEqual(pins_md_text(page([line_pin(1, el=bad)])), plain)


class SharedPart(unittest.TestCase):
    """'공통 부품: <path>:<lo>-<hi>' is a line an agent acts on: printed only for a plain relative path
    (limn.builds.figure_map's canonical rule, no dot-named part), never as the stored text alone."""

    def part_of(self, el, impl_scope):
        """The note cell of a row for a pin with el whose document's folder the edge gave as impl_scope."""
        md = pins_md_text(page([line_pin(1, el=el, note="n")], {1: facts(impl_scope=impl_scope)}))
        return next(line for line in md.splitlines() if line.startswith("| 1 |"))

    def test_the_part_is_printed_from_the_placed_location_and_the_stored_lines(self):
        """The renderer joins impl_scope (the document's folder) and el.impl.file as text: lib/components.py under
        figs/."""
        self.assertTrue(self.part_of(EL7, "figs").endswith("n ⏎ 공통 부품: figs/lib/components.py:410-470 |"))

    def test_an_element_without_a_note_shows_the_part_alone_after_its_label(self):
        """No note: «label» then the part, with no stray separator."""
        md = pins_md_text(page([line_pin(1, el=EL7, note="")], {1: facts(impl_scope="figs")}))
        self.assertIn("| «7월» 공통 부품: figs/lib/components.py:410-470 |", md)

    def test_no_scope_means_no_part_and_never_the_stored_file(self):
        """Without impl_scope (the pin's document is not served, so its folder is unknown) the stored impl.file is not
        printed in its place (it is relative to the document's folder, not to --manuscript): the row is as if the
        element had no shared part."""
        row = self.part_of(EL7, None)
        self.assertNotIn("공통 부품", row)
        self.assertNotIn("lib/components.py", row)
        self.assertTrue(row.endswith("| «7월» n |"))

    def test_an_element_without_impl_has_no_part(self):
        """el without impl: nothing to print even when a location was given."""
        el = {k: v for k, v in EL7.items() if k != "impl"}
        self.assertNotIn("공통 부품", self.part_of(el, "figs"))

    def test_a_stored_file_that_is_not_a_canonical_relative_path_is_omitted(self):
        """A line that predates parse_el, or a hand edit: '..', '.', an empty part, a leading '/', a backslash, a NUL
        and a path longer than the map's limit are each left out, whatever location the edge placed."""
        too_long = "d/" * (figmap.MAP_MAX_PATH // 2) + "x.py"
        for bad in (
            "../secret.py",
            "lib/../../secret.py",
            "./a.py",
            "lib/./a.py",
            "lib//a.py",
            "/etc/passwd",
            "lib/a.py/",
            "",
            "lib\\a.py",
            "a\x00.py",
            too_long,
        ):
            with self.subTest(file=bad[:30]):
                self.assertNotIn("공통 부품", self.part_of(el_with_impl(bad), "figs"))

    def test_a_path_with_a_dot_named_part_is_omitted(self):
        """.git, a hidden folder or a hidden file anywhere in the path stays out of an agent's work list."""
        for bad in (".git/config", "lib/.env", ".hidden.py", "lib/..x/a.py", "a/.b"):
            with self.subTest(file=bad):
                self.assertNotIn("공통 부품", self.part_of(el_with_impl(bad), "figs"))

    def test_a_scope_that_is_hostile_is_omitted_too(self):
        """The renderer judges the joined path itself: an impl_scope with '..', an absolute path, a dot part or a
        backslash drops the part; the manuscript root ("") is a fine scope."""
        for bad in ("..", "../x", "/etc", "figs/.git", "figs//x", "figs\\x", ".figs"):
            with self.subTest(scope=bad):
                self.assertNotIn("공통 부품", self.part_of(EL7, bad))
        self.assertIn("공통 부품: lib/components.py:410-470", self.part_of(EL7, ""))

    def test_lines_outside_what_a_request_could_have_stored_are_omitted(self):
        """1 <= lo <= hi <= MAP_MAX_LINE (parse_el's bound): zero, negative, reversed and huge ranges print nothing."""
        for lo, hi in ((0, 5), (-3, 5), (9, 3), (1, figmap.MAP_MAX_LINE + 1), (1, 10**400)):
            with self.subTest(lo=lo, hi=hi):
                self.assertNotIn("공통 부품", self.part_of(el_with_impl("lib/components.py", lo, hi), "figs"))
        self.assertIn(
            "공통 부품",
            self.part_of(el_with_impl("lib/components.py", 1, figmap.MAP_MAX_LINE), "figs"),
        )

    def test_a_pipe_in_the_path_cannot_add_a_column(self):
        """The part goes through md_cell like every cell."""
        row = self.part_of(el_with_impl("lib/a|b.py"), "figs")
        self.assertIn("공통 부품: figs/lib/a\\|b.py:410-470", row)

    def test_the_join_is_text_only_under_the_document_folder(self):
        """shared_part_path(scope, file): scope/file as text, file alone for the manuscript root, None for what may not
        be printed."""
        self.assertEqual(render.shared_part_path("figs", "lib/components.py"), "figs/lib/components.py")
        self.assertEqual(render.shared_part_path("", "lib/components.py"), "lib/components.py")
        self.assertEqual(render.shared_part_path("a/b", "c.py"), "a/b/c.py")
        for scope, file in (
            ("figs", "../x.py"),
            ("figs", "/x.py"),
            ("figs", ".git/x"),
            (".figs", "x.py"),
            ("fi\\gs", "x.py"),
            ("figs", ""),
        ):
            with self.subTest(scope=scope, file=file):
                self.assertIsNone(render.shared_part_path(scope, file))


class FigureSections(unittest.TestCase):
    """The section title and the document list say what a figure document is."""

    def test_a_figure_section_is_titled_as_a_figure_and_the_view_only_title_is_unchanged(self):
        """A document with an element map gets the title suffix — 그림(요소 지도) and keeps the stamp word 그림 (not
        built from source); a view-only PDF keeps — 보기 전용 PDF(줄 번호 없음) exactly; a LaTeX section gets neither."""
        fg = DocHeading(
            "fig", "그림", "figs/out/figures.limnmap.json", view_only=False, builds_from_source=False,
            head="abc1234", built_at="2026-09-26 10:00", has_element_map=True,
        )  # fmt: skip
        rv = DocHeading("rv", "리뷰", "review.pdf", view_only=True, builds_from_source=False, head=None, built_at=None)
        region = {
            "id": 2,
            "pdf": "/ms/review.pdf",
            "page": 1,
            "frac": [0.1, 0.1, 0.2, 0.2],
            "kind": "region",
            "note": "r",
        }
        rows = [line_pin(1, el=EL7), region, line_pin(3)]
        pin_facts = {1: facts(doc_key="fig"), 2: facts(doc_key="rv", location=""), 3: facts()}
        lines = pins_md_text(page(rows, pin_facts, docs=(MAIN, fg, rv))).splitlines()
        self.assertIn("## 그림 · `fig` · `figs/out/figures.limnmap.json` — 그림(요소 지도)", lines)
        self.assertIn("기준: abc1234 · 그림 2026-09-26 10:00", lines)
        self.assertIn("## 리뷰 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)", lines)
        self.assertIn("## 본문 · `main` · `main.tex`", lines)

    def test_a_heading_without_the_new_field_is_no_figure(self):
        """has_element_map defaults to False: headings built before the field keep their titles."""
        self.assertFalse(MAIN.has_element_map)
        self.assertFalse(PDF.has_element_map)

    def test_a_figure_document_is_not_labelled_view_only_in_the_document_list(self):
        """Figure documents take line pins, so the list says '보기 전용' for the PDF document only - the figure's entry is
        its name, key and count, as any document with line pins."""
        rows = [line_pin(1, el=EL7), region_pin(2, doc_pdf="/ms/review.pdf")]
        md = pins_md_text(
            page(rows, {1: facts(doc_key="fig"), 2: facts(doc_key="rv", location="")}, docs=(MAIN, FIG, PDF))
        )
        self.assertIn("문서: 본문(`main`) 0건 · 그림(`fig`) 1건 · 리뷰(`rv`, 보기 전용) 1건", md)
        self.assertNotIn("그림(`fig`, 보기 전용)", md)

    def test_the_stamp_word_is_decided_by_builds_from_source_alone(self):
        """A figure heading whose pages are read in says 그림; had it been built from source it would say 빌드 -
        has_element_map changes the title and nothing else."""
        for builds, word in ((False, "그림"), (True, "빌드")):
            with self.subTest(builds_from_source=builds):
                fg = dataclasses.replace(FIG, builds_from_source=builds, head="abc1234", built_at="2026-09-26 10:00")
                md = pins_md_text(page([line_pin(1, el=EL7)], {1: facts(doc_key="fig")}, docs=(MAIN, fg)))
                self.assertIn("기준: abc1234 · %s 2026-09-26 10:00" % word, md)
                self.assertIn(" — 그림(요소 지도)", md)

    def test_a_view_only_heading_that_also_says_element_map_keeps_the_view_only_title(self):
        """view_only wins the title as before: the suffix a viewer-only PDF has is never replaced."""
        both = dataclasses.replace(PDF, has_element_map=True)
        md = pins_md_text(
            page([region_pin(1, doc_pdf="/ms/review.pdf")], {1: facts(doc_key="rv", location="")}, docs=(MAIN, both))
        )
        self.assertIn("## 리뷰 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)", md)
        self.assertNotIn("요소 지도", md)


class SingleDocumentSections(unittest.TestCase):
    """One served document: only a figure document is sectioned, so its title and 기준 line are always shown."""

    def test_a_figure_only_instance_shows_its_titled_section_and_stamp(self):
        """The one document is a figure: the sheet is sectioned - the document list, the title with — 그림(요소 지도) and its
        기준 line - though there is no second document."""
        fg = dataclasses.replace(FIG, head="abc1234", built_at="2026-09-26 10:00")
        md = pins_md_text(page([line_pin(1, el=EL7)], {1: facts(doc_key="fig")}, docs=(fg,)))
        lines = md.splitlines()
        self.assertIn("문서: 그림(`fig`) 1건", md)
        self.assertIn("## 그림 · `fig` · `figs/out/figures.limnmap.json` — 그림(요소 지도)", lines)
        self.assertEqual(
            lines[lines.index("## 그림 · `fig` · `figs/out/figures.limnmap.json` — 그림(요소 지도)") + 1],
            "기준: abc1234 · 그림 2026-09-26 10:00",
        )

    def test_a_figure_only_instance_without_open_pins_is_sectioned_too(self):
        """No open pin: the sectioned sheet's '열린 핀 없음' line, as any several-document sheet without pins."""
        self.assertTrue(pins_md_text(page([], docs=(FIG,))).endswith("\n\n열린 핀 없음\n"))

    def test_a_single_latex_document_keeps_the_old_shape(self):
        """One LaTeX document: no subsections, the stamp in the header, the one table - byte for byte the unsectioned
        form."""
        stamped = dataclasses.replace(MAIN, head="abc1234", built_at="2026-09-26 09:59")
        md = pins_md_text(page([line_pin(1)], docs=(stamped,)))
        self.assertNotIn("\n## ", md)
        self.assertNotIn("\n문서: ", md)
        self.assertIn("\n기준: abc1234 · 빌드 2026-09-26 09:59\n", md)

    def test_a_single_view_only_pdf_document_keeps_the_old_shape(self):
        """One view-only PDF and no figure: still unsectioned, as before."""
        pdf = dataclasses.replace(PDF, head="bbb2222", built_at="2026-09-25 08:00")
        md = pins_md_text(
            page([region_pin(1, doc_pdf="/ms/review.pdf")], {1: facts(doc_key="rv", location="")}, docs=(pdf,))
        )
        self.assertNotIn("\n## ", md)
        self.assertNotIn("\n문서: ", md)
        self.assertIn("\n기준: bbb2222 · 빌드 2026-09-25 08:00\n", md)


class FigureGuidance(unittest.TestCase):
    """What the guidance says to do with a figure pin, a region pin on a figure, and a view-only PDF's pin."""

    def test_the_figure_clause_points_at_the_figure_repository_not_the_latex_document(self):
        """FIGURE_GUIDANCE says the fix is in the figure repository (or the person's answer) and never sends an agent to
        the LaTeX document."""
        self.assertIn("그림 저장소", render.FIGURE_GUIDANCE)
        self.assertIn("사람에게 묻", render.FIGURE_GUIDANCE)
        self.assertNotIn("LaTeX 문서에서 찾는다", render.FIGURE_GUIDANCE)

    def test_the_figure_clause_names_a_script_or_a_design_file_as_the_source(self):
        """The drawn-without-code sentence says the element may come from a script or a design file, so an agent does
        not search scripts for a graphic a design tool made."""
        self.assertIn("스크립트나 디자인 파일", render.FIGURE_GUIDANCE)

    def test_the_figure_clause_says_an_element_from_a_design_tool_is_reported_not_edited(self):
        """An element that comes from a design file has no code to edit: the clause tells the agent to report it, in the
        words SKILL.ko.md uses."""
        self.assertIn("요소가 디자인 도구에서 왔으면 고치지 말고 보고한다", render.FIGURE_GUIDANCE)

    def test_a_region_pin_on_a_figure_document_without_an_element_takes_the_figure_clause(self):
        """A pick that fell back because the map could not be read leaves a region pin without el on a figure document:
        it has no lines either, and its fix is not in a LaTeX document, so it too gets the figure clause and not the
        view-only one."""
        md = pins_md_text(page([region_pin(1)], {1: facts(doc_key="fig", location="")}, docs=(MAIN, FIG)))
        self.assertIn(render.FIGURE_GUIDANCE, md)
        self.assertNotIn(VIEW_ONLY_CLAUSE, md)
        self.assertNotIn("LaTeX 문서에서 찾는다", md)

    def test_a_view_only_pdfs_region_pin_keeps_its_clause_and_brings_no_figure_clause(self):
        """The view-only guidance is as before for a PDF document; the figure clause stays out."""
        md = pins_md_text(
            page([region_pin(1, doc_pdf="/ms/review.pdf")], {1: facts(doc_key="rv", location="")}, docs=(MAIN, PDF))
        )
        self.assertIn("보기 전용 PDF 의 핀은 줄 번호가 없다", md)
        self.assertIn("고칠 곳은 LaTeX 문서에서 찾는다", md)
        self.assertNotIn(render.FIGURE_GUIDANCE, md)

    def test_both_kinds_open_at_once_each_get_their_own_clause(self):
        """A view-only PDF's pin and a figure's region pin: the sheet says both, the view-only one first."""
        rows = [region_pin(1, doc_pdf="/ms/review.pdf"), region_pin(2)]
        md = pins_md_text(
            page(
                rows, {1: facts(doc_key="rv", location=""), 2: facts(doc_key="fig", location="")}, docs=(MAIN, PDF, FIG)
            )
        )
        line = guidance_line(md)
        self.assertIn(VIEW_ONLY_CLAUSE, line)
        self.assertTrue(line.endswith(render.FIGURE_GUIDANCE))

    def test_a_region_pin_under_an_unknown_document_is_a_view_only_one(self):
        """A region pin whose document is not configured is judged by its shape alone, as before: the view-only
        clause."""
        md = pins_md_text(page([region_pin(1)], {1: facts(doc_key="gone", location="")}))
        self.assertIn(VIEW_ONLY_CLAUSE, md)
        self.assertNotIn(render.FIGURE_GUIDANCE, md)

    def test_a_done_or_review_figure_pin_brings_no_clause(self):
        """Only open pins are worked: a closed element pin does not add the clause."""
        done = line_pin(1, el=EL7, done=True)
        self.assertNotIn(render.FIGURE_GUIDANCE, pins_md_text(page([done, line_pin(2)])))

    def test_two_element_pins_do_not_repeat_the_figure_clause(self):
        """The clause is one sentence whatever the number of figure pins."""
        md = pins_md_text(page([line_pin(1, el=EL7), line_pin(2, el=EL7)]))
        self.assertEqual(md.count(render.FIGURE_GUIDANCE), 1)


# ---------------------------------------------------------------- through server.py's wiring
#
# Pins.md as the server writes it after a pin write. These classes load server.py (helpers.ps) and drive the module
# through its bindings; the tests above call the module on its own.

# ---------------------------------------------------------------- pins.md v2 · quote (docs/handbook/api.md §메모 칸의 덧붙임)


class PinsMdV2(Base):
    """The rendered work list preserves pin location, note, and overlap presentation."""

    def test_relative_path_for_included_file(self):
        sub = self.src / "sections"
        sub.mkdir()
        f = sub / "intro.tex"
        f.write_text("line one\nline two\n", encoding="utf-8")
        pid = add_pin({"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n"}, dict(LOCAL_ACTOR)).record["id"]
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("`sections/intro.tex L1-L1`", md)
        self.assertEqual(self.pin(pid)["lo"], 1)

    def test_root_file_location_matches_basename(self):
        self.add(4, 5)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("`main.tex L4-L5`", md)

    def test_closed_pins_do_not_grow_pins_md(self):
        """Completed human-closed pins change the summary count without adding Markdown table rows."""
        self.add(4, 5)
        before = len(ps.APP.C.pins_md.read_text(encoding="utf-8").splitlines())
        for i in range(20):
            pid = self.add(4, 5, note="c%d" % i)
            # closed by a human = done (if an agent closes it, it stays in the table as awaiting review)
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(
                    ps.APP.pin_lifecycle.context().store, {"login": "a@example.com", "name": "A"}, "close", pid
                ),
                CloseRequest(),
            )
        after = len(ps.APP.C.pins_md.read_text(encoding="utf-8").splitlines())
        self.assertEqual(before, after)
        self.assertIn("닫힌 핀 20건", ps.APP.C.pins_md.read_text(encoding="utf-8"))

    def test_newline_in_note_becomes_line_separator(self):
        self.add(4, 5, note="첫줄\n둘째줄")
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("첫줄 ⏎ 둘째줄", md)
        self.assertNotIn("첫줄\n둘째줄", md)
        for line in md.splitlines():
            if line.startswith("| ") and "⏎" in line:
                self.assertEqual(line.count("|"), 6)  # 5-column table: 6 pipes

    def test_overlap_symbol_in_number_column(self):
        p1 = self.add(4, 9)
        self.add(4, 5)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("#%d 범위 안" % p1, md)
        self.assertNotIn("⊂", md)

    def test_close_guidance_shows_reply_ref_body(self):
        """pins.md shows a close example with a body (reply, ref, changes) - an agent reading only pins.md must see how to close."""
        # bug: the close guidance in pins.md only showed a body-less curl, so an agent reading only this
        # file had no way to know how to leave a reply/ref (§Leaving a reason when closing — it must match the same shape as SKILL.md).
        self.add(4, 5)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("curl -X POST -H 'Content-Type: application/json'", md)
        self.assertIn(
            '-d \'{"reply":"무엇을 고쳤는지(≤500자)","ref":"PR #12 (커밋 해시)",'
            '"changes":[{"file":"main.tex","lo":12,"hi":14}]}\'',
            md,
        )  # v0.3: one commit per pin, optional changes
        self.assertIn("http://127.0.0.1:%d/api/pins/N/close" % ps.APP.C.port, md)
        self.assertIn("본문 생략", md)  # notes that the old way of omitting the body still works

    def test_quote_shown_only_for_single_long_raw_line(self):
        long_line = "x" * 650
        f = self.src / "long.tex"
        f.write_text(long_line + "\n", encoding="utf-8")
        pid = add_pin(
            {"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n", "scope": "raw", "quote": "짧은 인용"},
            dict(LOCAL_ACTOR),
        ).record["id"]
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("«짧은 인용»", md)
        # a short line (<=600 chars) doesn't get a quote attached even if one is present
        rows = records(ps.APP.snapshot_pins())
        for r in rows:
            if r["id"] == pid:
                r["lo"] = r["hi"] = 4
                r["quote"] = "안 보여야 함"
                r["file"] = str(self.main)
        write_records(rows)
        md2 = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("«안 보여야 함»", md2)

    def test_truncate_quote_appends_ellipsis_only_when_cut(self):
        self.assertEqual(mapping.truncate_quote("짧음", 60), "짧음")
        self.assertNotIn("…", mapping.truncate_quote("짧음", 60))
        long = "x" * 90
        cut = mapping.truncate_quote(long, 60)
        self.assertEqual(cut, "x" * 59 + "…")
        # bug: it used to come out to 61 chars (60 + …) — the design calls for <=60 chars
        self.assertEqual(len(cut), 60)
        self.assertEqual(mapping.truncate_quote("x" * 60, 60), "x" * 60)  # exactly at the boundary, nothing is appended

    def test_quote_truncated_with_ellipsis_in_pins_md(self):
        """A line pin keeps its quote up to 160 characters for the viewer (issue #185), while pins.md still quotes 60
        with an ellipsis - the agent's search hint is unchanged. A stored quote already cut at 60 renders as it was."""
        # bug: when a quote was cut past 60 chars, the missing ellipsis made it look like a complete sentence.
        long_line = "y" * 650
        f = self.src / "long2.tex"
        f.write_text(long_line + "\n", encoding="utf-8")
        pid = add_pin(
            {"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n", "scope": "raw", "quote": "가" * 90},
            dict(LOCAL_ACTOR),
        ).record["id"]
        self.assertEqual(self.pin(pid)["quote"], "가" * 90)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("«" + "가" * 59 + "…»", md)
        self.assertNotIn("가" * 60, md)
        pid2 = add_pin(
            {"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n2", "scope": "raw", "quote": "나" * 200},
            dict(LOCAL_ACTOR),
        ).record["id"]
        self.assertEqual(self.pin(pid2)["quote"], "나" * 159 + "…")
        rows = records(ps.APP.snapshot_pins())
        for r in rows:
            if r["id"] == pid2:
                r["quote"] = "다" * 59 + "…"  # a pin saved before the limit was raised
        write_records(rows)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        # render_quote doesn't re-truncate a value that already has … appended
        self.assertIn("«" + "다" * 59 + "…»", md)

    def test_location_col_escapes_pipe_in_filename(self):
        # bug: a pipe in the filename in the location column could break the table's column structure (note/quote were already escaped).
        sub = self.src / "a|b"
        sub.mkdir()
        f = sub / "c.tex"
        f.write_text("line one\n", encoding="utf-8")
        add_pin({"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n"}, dict(LOCAL_ACTOR)).record["id"]
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("a\\|b/c.tex L1-L1", md)
        for line in md.splitlines():
            if "a\\|b" in line:
                # 6 separators for a 5-column table + 1 escaped pipe in the filename ("\|" is still a '|' character) = 7.
                self.assertEqual(line.count("|"), 7)
                self.assertNotIn("a|b/c.tex", line)  # the unescaped original fragment must not appear

    def test_range_col_escapes_pipe_in_env_kind(self):
        # bug (should): the location column (loc_label) and quote (render_quote) escaped pipes,
        # but the range column (range_label) returned the env name as-is — so storing kind='env:x|y'
        # made the pins.md table row exceed 6 columns instead of staying at 6, breaking the table.
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "n", "scope": "env", "kind": "env:x|y"},
            dict(LOCAL_ACTOR),
        ).record["id"]
        self.assertEqual(md_render.range_label(self.pin(pid)), "env:x\\|y")
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        for line in md.splitlines():
            if "env:x" in line:
                self.assertIn("env:x\\|y", line)
                # 6 separators for a 5-column table + 1 escaped pipe in the range column = 7 (same arithmetic as the filename-column test).
                self.assertEqual(line.count("|"), 7)

    def test_every_cell_escapes_pipe_and_newline(self):
        # design 5: exhaustively cover every column — kind (range column, both env and non-env branches),
        # filename, note, quote. Any column breaks the row if a raw '|' or newline gets through.
        add_pin(
            {
                "file": str(self.main),
                "lo": 4,
                "hi": 5,
                "page": 1,
                "note": "a|b\nc",
                "scope": "env",
                "kind": "env:x|y\nz",
            },
            dict(LOCAL_ACTOR),
        ).record["id"]
        add_pin(
            {"file": str(self.main), "lo": 8, "hi": 8, "page": 1, "note": "n", "kind": "k|1\r\nk2"}, dict(LOCAL_ACTOR)
        ).record["id"]
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        rows = [ln for ln in md.splitlines() if ln.startswith("| ") and "main.tex" in ln]
        self.assertEqual(len(rows), 2)
        for ln in rows:
            unescaped = re.sub(r"\\\|", "", ln)
            self.assertEqual(unescaped.count("|"), 6, ln)
        self.assertIn("env:x\\|y z", rows[0])
        self.assertIn("a\\|b ⏎ c", rows[0])
        self.assertIn("k\\|1 k2", rows[1])
        self.assertEqual(md_render.md_cell("a|b\r\nc"), "a\\|b c")

    def test_legend_absent_when_no_symbols(self):
        self.add(4, 5)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("기호:", md)

    def test_open_pins_table_has_five_columns(self):
        self.add(4, 5)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        for line in md.splitlines():
            if line.startswith("| ") and "쪽" not in line and "#" not in line[:4]:
                self.assertEqual(line.count("|"), 6)


# ---------------------------------------------------------------- base commit/build at the top of pins.md (docs/handbook/api.md §머리줄)


class BuildHeadInPinsMd(Base):
    """The work list includes a concise build head only when its source files exist."""

    def test_head_line_present_when_head_and_built_at_known(self):
        (ps.APP.C.state / "head.txt").write_text("abc1234", encoding="utf-8")
        (ps.APP.C.state / "built_at.txt").write_text("2026-09-22 10:00:00", encoding="utf-8")
        self.add()
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("기준: abc1234 · 빌드 2026-09-22 10:00:00", md)
        self.assertIn("다른 체크아웃에서 처리하면 먼저 `git rev-parse --short HEAD` 가 같은지 확인", md)

    def test_head_line_omitted_when_files_missing(self):
        self.add()
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("기준:", md)
        self.assertNotIn("다른 체크아웃에서", md)

    def test_head_line_omitted_for_dash_placeholder(self):
        # _build() writes '-' to head.txt when it's not a git repo — in that case there's nothing to show for "기준" (base).
        (ps.APP.C.state / "head.txt").write_text("-", encoding="utf-8")
        (ps.APP.C.state / "built_at.txt").write_text("2026-09-22 10:00:00", encoding="utf-8")
        self.add()
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("기준:", md)

    def test_head_block_adds_at_most_two_lines(self):
        without = ps.APP.pin_markdown.pins_md_text([]).splitlines()
        (ps.APP.C.state / "head.txt").write_text("abc1234", encoding="utf-8")
        (ps.APP.C.state / "built_at.txt").write_text("2026-09-22 10:00:00", encoding="utf-8")
        withit = ps.APP.pin_markdown.pins_md_text([]).splitlines()
        self.assertLessEqual(len(withit) - len(without), 2)


# ---------------------------------------------------------------- showing the author only when needed (docs/handbook/api.md §메모 칸의 덧붙임)


class AuthorPrefixInPinsMd(Base):
    """Author labels appear only when open pins belong to multiple authors."""

    # the author prefix has the form '[name] ' (§api.md note has [author] up front) — the old '@name: '
    # shape was misread as an @-mention (observed: '@Wendy Kim: …' in pins.md looked like a mention).
    def test_single_author_has_no_prefix(self):
        self.add(note="n", actor={"login": "alice@example.com", "name": "Wendy"})
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("[Wendy]", md)

    def test_multiple_authors_get_prefix(self):
        self.add(4, 5, note="n1", actor={"login": "alice@example.com", "name": "Wendy"})
        self.add(8, 8, note="n2", actor={"login": "bob@example.com", "name": "Bob"})
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("[Wendy] n1", md)
        self.assertIn("[Bob] n2", md)

    def test_same_author_twice_does_not_trigger_prefix(self):
        self.add(4, 5, note="n1", actor={"login": "alice@example.com", "name": "Wendy"})
        self.add(8, 8, note="n2", actor={"login": "alice@example.com", "name": "Wendy"})
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("[Wendy]", md)

    def test_legacy_pin_without_author_counts_as_one_group(self):
        pid1 = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "legacy"}, dict(LOCAL_ACTOR)
        ).record["id"]
        rows = records(ps.APP.snapshot_pins())
        for r in rows:
            if r["id"] == pid1:
                r.pop("author", None)
        write_records(rows)
        self.add(8, 8, note="n2", actor={"login": "bob@example.com", "name": "Bob"})
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("[Bob] n2", md)
        self.assertNotIn("[None]", md)
        self.assertIn("legacy", md)

    def test_closed_pins_excluded_from_author_count(self):
        """An author present only in review must not trigger author prefixes for the sole open-pin author."""
        # a closed pin's author isn't shown in the open table, so it must be excluded from the count too (judged by open pins only).
        pid = self.add(4, 5, note="n1", actor={"login": "alice@example.com", "name": "Wendy"})
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid), CloseRequest()
        )
        self.add(8, 8, note="n2", actor={"login": "bob@example.com", "name": "Bob"})
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("[Bob]", md)


class InstanceIdInPinsMd(Base):
    """Disk and HTTP work lists show the instance identity and remote guidance."""

    def test_disk_header_has_paper_and_repo_line(self):
        set_config(label="A-DEMO", repo="git@github.com:example-lab/paper-a.git")
        self.add()
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        lines = md.splitlines()
        src_idx = next(i for i, ln in enumerate(lines) if ln.startswith("원고: `"))
        self.assertEqual(lines[src_idx + 1], "논문: A-DEMO · 저장소: git@github.com:example-lab/paper-a.git")

    def test_header_shows_placeholder_without_repo(self):
        set_config(label="paper-a", repo=None)
        self.add()
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("논문: paper-a · 저장소: (없음)", md)

    def test_guidance_mentions_remote_check_only_when_repo_known(self):
        set_config(label="A-DEMO", repo="git@github.com:example-lab/paper-a.git")
        self.add()
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("git remote get-url origin", md)
        self.assertIn("다르면 다른 논문의 핀이니 멈춘다", md)

    def test_guidance_omits_remote_check_without_repo(self):
        set_config(label="paper-a", repo=None)
        self.add()
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("git remote get-url origin", md)

    def test_get_pins_md_endpoint_also_has_id_line(self):
        set_config(label="A-DEMO", repo="git@github.com:example-lab/paper-a.git")
        self.add()
        out = self.talk(req("GET", "/pins.md"))
        body = out.split(b"\r\n\r\n", 1)[1].decode("utf-8")
        self.assertIn("논문: A-DEMO · 저장소: git@github.com:example-lab/paper-a.git", body)


class ClaimText(Base):
    """pins.md shows a claim as '처리 중(<name>, 약 N분)', the estimate rounded up to 5 minutes, or '예상 초과'."""

    def test_pins_md_claim_text(self):
        """Claim text rounds remaining estimates to five-minute steps and marks overdue leases in persisted Markdown."""
        now = 1_790_000_000.0
        r = {"claimed_by": {"name": "Kim"}}
        self.assertEqual(md_render.claim_md(dict(r), now), "처리 중(Kim)")
        for left_s, want in (
            (14 * 60 + 10, "약 15분"),
            (3 * 60, "약 5분"),
            (15 * 60, "약 15분"),
            (16 * 60, "약 20분"),
            (-60, "예상 초과"),
        ):
            self.assertEqual(md_render.claim_md(dict(r, eta_ts=now + left_s), now), "처리 중(Kim, %s)" % want)
        self.assertEqual([md_render.ceil5(m) for m in (0, 0.2, 5, 5.01, 14.9, 23)], [5, 5, 5, 10, 15, 25])
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(ps.APP.pin_claims.context().store, {"login": "k", "name": "에이전트 A"}, "claim", pid),
            *claims_input.parse_claim_body({"eta_min": 15}),
        )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("처리 중(에이전트 A, 약 15분)", md)


class BadgeWordsInPinsMd(Base):
    """pins.md's number column joins the badge words with ' · ' and uses no symbols."""

    def test_pins_md_number_column_uses_words(self):
        """Overlap, claim, and edit badges remain readable contract words with stable explanatory guidance."""
        a = self.add(4, 9)
        b = self.add(4, 9)
        c = self.add(5, 6)
        edit_pin(c, {"note": "고침", "base_rev": self.pin(c)["rev"]}, dict(LOCAL_ACTOR))
        ps.APP.pin_claims.claim_pin(
            c,
            post_authority(ps.APP.pin_claims.context().store, {"login": "k", "name": "Kim"}, "claim", c),
            *claims_input.parse_claim_body({"eta_min": 10}),
        )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("| %d · #%d와 같은 범위 |" % (a, b), md)
        self.assertIn("| %d · #%d과 같은 범위 |" % (b, a), md)
        self.assertIn("| %d · #%d 범위 안 · 처리 중(Kim, 약 10분) · 수정됨 |" % (c, a), md)
        for sym in ("⊂", "∩", "⏳", "✎", "⚠"):
            self.assertNotIn(sym, md)
        self.assertIn("표시: '#N 범위 안'·'#N과 같은 범위' = N과 한 번에 고치고 둘 다 닫는다", md)


class QuestionsInPinsMd(Base):
    """pins.md marks question pins and shows only the current round of a pin's thread, escaped into the table."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    def test_pins_md_marks_questions_and_shows_current_round_of_thread(self):
        """Question rows escape and truncate current-round replies without leaking messages from a previous round."""
        q = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "구간의 정의는?", "kind_req": "question"},
            dict(self.S),
        ).record["id"]
        for i in range(5):
            ps.APP.pin_lifecycle.reply_pin(
                q,
                "답글 %d\n둘째 줄 | 파이프" % i,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "reply", q),
            )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % q))
        self.assertIn("| %d · 질문 |" % q, row)
        self.assertIn("[스레드 5건, 앞 2건은 GET /api/pins/%d]" % q, row)
        self.assertIn("Bob Park: 답글 4 둘째 줄 \\| 파이프", row)  # a newline collapses, | gets escaped
        self.assertNotIn("답글 1", row)
        self.assertEqual(row.count("|") - row.count("\\|"), 6)  # still a 5-column table
        self.assertIn("/api/pins/N/reply", md)
        self.assertIn("'질문' = 고칠 곳이 아니라 물음이다", md)
        ps.APP.pin_lifecycle.close_pin(
            q,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "close", q),
            CloseRequest(reply="답했다"),
        )
        ps.APP.pin_lifecycle.reopen_pin(
            q, post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "reopen", q)
        )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % q))
        self.assertNotIn("[스레드", row)  # messages from before the close aren't shown


class ReviewInPinsMd(Base):
    """pins.md lists pins awaiting review in their own section at the bottom and counts them in the header line."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    def test_pins_md_review_section_and_header(self):
        """Review pins occupy a separate escaped table and disappear from that section after confirmation."""
        a = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "q", "kind_req": "question"}, dict(self.S)
        ).record["id"]
        b = self.add(8, 9)
        ps.APP.pin_lifecycle.close_pin(
            a,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", a),
            CloseRequest(reply="구간은 0 을 포함 | 유의하지 않음", ref="PR #12"),
        )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("열린 핀 1건  ·  검토 대기 1건(맨 아래, 처리하지 않는다)  ·  닫힌 핀 0건", md)
        sec = md[md.index("## 검토 대기 1건") :]
        self.assertIn("| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |", sec)
        self.assertIn(
            "| %d · 질문 | `main.tex L4-L5` | Bob Park | 구간은 0 을 포함 \\| 유의하지 않음 (PR #12) |" % a, sec
        )
        opn = md[: md.index("## 검토 대기")]
        starts = [
            ln.split("|")[1].strip() for ln in opn.splitlines() if ln.startswith("| ") and not ln.startswith("| #")
        ]
        self.assertEqual(starts, [str(b)])  # only open pins appear in the open table
        self.assertIn('`"review":true`', md)
        self.assertIn("검토 대기 핀은 다시 처리하지 않는다", md)
        ps.APP.pin_lifecycle.confirm_pin(
            a, post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "confirm", a)
        )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("## 검토 대기", md)
        # with nothing awaiting review, the header line reverts to the old look
        self.assertIn("열린 핀 1건  ·  닫힌 핀 1건", md)


class AddressedInPinsMd(Base):
    """pins.md marks pins addressed to a person ('→ @이름') and tells agents to skip them; an agent assignee makes the
    tag 'fyi', and a pin without the assignee field falls back to the kind rule."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    W = {"login": "wendy@example.com", "name": "Wendy Kim"}

    def setUp(self):
        super().setUp()

    def test_pins_md_marks_human_addressed_pins_and_tells_agents_to_skip(self):
        ps.APP.people_directory.record(dict(self.W))
        a = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "note": "@Wendy Kim 이 구간 맞나요?", "kind_req": "question"},
            dict(self.S),
        ).record["id"]
        self.add(8, 9)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % a))
        self.assertIn("| %d · → @Wendy Kim · 질문 |" % a, row)  # priority: reopened > -> @ > question
        self.assertIn("`→ @이름` 이 붙은 핀 1건은 담당이 사람인", md)
        self.assertIn("명시적으로 시키지 않으면 건너뛴다", md)
        rows = ps.APP.pin_listing.pins_payload(ps.APP.snapshot_pins(), True)
        self.assertEqual(next(r for r in rows if r["id"] == a)["addressed"], [self.W["login"]])

    # ---- assignee — docs/handbook/api.md §담당. Guessing the skip rule from free text was ambiguous (A-DEMO #43).
    def test_assignee_person_is_addressed_agent_is_fyi_and_legacy_falls_back(self):
        ps.APP.people_directory.record(dict(self.W))
        ps.APP.people_directory.record(dict(self.S))
        note = "이거 콜링 제대로 작동하나 @Bob Park 확인 부탁합니다"
        legacy = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": note}, dict(self.W)).record["id"]
        person = add_pin(
            {"file": str(self.main), "lo": 8, "hi": 9, "note": note, "assignee": self.S["login"]}, dict(self.W)
        ).record["id"]
        agent = add_pin(
            {
                "file": str(self.main),
                "lo": 2,
                "hi": 3,
                "note": "@Bob Park 질문 참고",
                "kind_req": "question",
                "assignee": "agent",
            },
            dict(self.W),
        ).record["id"]
        rows = {r["id"]: r for r in ps.APP.pin_listing.pins_payload(ps.APP.snapshot_pins(), True)}
        self.assertNotIn("assignee", rows[legacy])  # legacy pin: no field -> inferred per #87 (fix request = fyi)
        self.assertEqual((rows[legacy]["addressed"], rows[legacy]["fyi"]), ([], [self.S["login"]]))
        self.assertEqual((rows[person]["addressed"], rows[person]["fyi"]), ([self.S["login"]], []))
        # even a question is fyi if the assignee is an agent
        self.assertEqual((rows[agent]["addressed"], rows[agent]["fyi"]), ([], [self.S["login"]]))
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")

        def line(pid):
            """The pins.md table row for pin pid."""
            return next(ln for ln in md.splitlines() if ln.startswith("| %d " % pid))

        self.assertIn("| %d · 참고 @Bob Park |" % legacy, line(legacy))
        self.assertIn("| %d · → @Bob Park |" % person, line(person))
        self.assertIn("| %d · 참고 @Bob Park · 질문 |" % agent, line(agent))
        self.assertIn("`→ @이름` 이 붙은 핀 1건은 담당이 사람인", md)
        self.assertIn("'→ @이름' = 담당이 사람인 핀", md)


# ---------------------------------------------------------------- pins.md's claim and remote-agent token instructions (v0.2.1 QA)


class PinsMdInstructions(AccessBase):
    """The work list places action guidance and token instructions next to pin rows."""

    def test_claim_instruction_next_to_close(self):
        self.add()
        lines = ps.APP.C.pins_md.read_text(encoding="utf-8").splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("처리한 핀은 닫는다"))
        self.assertIn("/api/pins/N/claim", lines[i + 1])
        self.assertIn('"eta_min"', lines[i + 1])
        self.assertEqual(lines[i + 1], md_render.claim_guidance("http://127.0.0.1:18999"))
        self.assertEqual(lines[i + 2], md_render.TOKEN_GUIDANCE)

    def test_remote_agents_are_told_to_use_a_token(self):
        self.add()
        _, tok = token_create(ps.APP.C.state, "ci")
        code, md = self.call("GET", "/pins.md", token=tok, headers={"Host": TS_HOST})
        self.assertEqual(code, 200)
        self.assertIn("https://%s/api/pins/N/claim" % TS_HOST, md)
        self.assertIn("테일넷 주소", md_render.TOKEN_GUIDANCE)
        self.assertIn("403", md_render.TOKEN_GUIDANCE)
        self.assertEqual(md.splitlines().count(md_render.TOKEN_GUIDANCE), 1)


if __name__ == "__main__":
    unittest.main()

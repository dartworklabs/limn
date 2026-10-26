"""Verdict pins in what agents read (docs/superpowers/specs/2026-10-26-verdict-pins.md §pins.md, D12): the number-cell
marker and its '(쪽 전체)', the memo cell of a verdict-only pin, the legend entry and the guidance clause - from the
pure renderer (limn.pins.listing.render), then through the server's pins.md on disk with several documents.

Run: uv run pytest -q src/limn/pins/listing/tests/test_verdicts.py
"""

import json
import unittest

from limn.documents.verdicts import verdicts_path
from limn.pins.listing.render import (
    LEGEND,
    SUGGEST_LEGEND,
    VERDICT_LEGEND,
    DocHeading,
    PinFacts,
    PinsMdInput,
    pins_md_text,
    verdict_guidance,
)
from limn.runtime.documents import Doc

from helpers import MINI_PDF, ps
from helpers_access import BOB, AccessBase
from helpers_figure import BUILD1, SCRIPT, figure_doc, viewer_map, write_build

MAIN = DocHeading("main", "본문", "main.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
FIG = DocHeading("fig", "그림", "figs/out/figures.limnmap.json", False, False, None, None, has_element_map=True)
RV = DocHeading("rv", "리뷰", "review.pdf", view_only=True, builds_from_source=False, head=None, built_at=None)
NOW = 1_790_000_000.0
# The spec's two contract strings (docs/superpowers/specs/2026-10-26-verdict-pins.md §pins.md), word for word, with
# <base> as the spec writes it.
SPEC_LEGEND = (
    "'판정 X' = 작성자가 버튼으로 고른 판정이다(메모 첫 낱말보다 앞선다) · "
    "'(쪽 전체)' = 그 쪽의 그림(그림 문서) 또는 그 쪽(보기 전용 PDF)에 대한 판정"
)
SPEC_GUIDANCE = (
    "판정 핀(번호 칸 '판정 X', 그리고 그 저장소가 첫 낱말 규칙을 쓰면 메모 첫 낱말이 판정 낱말인 옛 핀)은 그 문서 저장소의 규칙대로 처리한다 · "
    "두 꼴이 함께 있으면 '판정 X'가 앞선다 · "
    "한 대상의 판정은 그 대상으로 풀리는 판정 핀(닫힌 것도, GET <base>/api/pins?all=1) 가운데 번호가 가장 큰 핀이다 · "
    "그보다 작은 열린 판정 핀은 실행하지 않고 '#N 판정이 앞섭니다' 답글을 남기고 닫는다 · "
    "사람 담당·남이 처리 중인 판정 핀은 순서에는 넣되 잡거나 닫지 않고, 그 대상은 기다린다 · "
    "같은 대상의 나머지 열린 판정 핀을 잡고 시작하고, 내보내기 직전에 다시 확인한다 · "
    "닫을 때 답 첫 줄에 '대상: <대상 ID>' 를 적는다 · "
    "대상을 풀 수 없는 더 큰 번호의 판정 핀이 있으면 그 대상은 실행하지 않고 답글로 묻는다"
)


def row(pid=41, **extra):
    """An open line pin on main.tex L4-L5 with an empty note, and whatever else is given."""
    return {"id": pid, "file": "/ms/main.tex", "lo": 4, "hi": 5, "page": 1, "note": "", **extra}


def figure_row(pid=41, path=("B2",), **extra):
    """An open figure pin on the drawing script whose el is the element at the end of path."""
    el = {"id": path[-1], "path": list(path)}
    return {"id": pid, "file": "/ms/figs/src/B2.py", "lo": 12, "hi": 140, "page": 1, "note": "", "el": el, **extra}


def pdf_row(pid=41, frac=(0, 0, 1, 1), **extra):
    """An open region pin on the view-only PDF's page 3."""
    return {
        "id": pid,
        "pdf": "/ms/review.pdf",
        "name": "review.pdf",
        "kind": "region",
        "page": 3,
        "frac": list(frac),
        "note": "",
        **extra,
    }


def facts(doc_key="main", **extra):
    """PinFacts of a plain pin in document doc_key, nothing else decided about it."""
    base = dict(
        doc_key=doc_key, location="main.tex", line_len=None, badge="", reopened=False, addressed=(), fyi=(), round=()
    )
    base.update(extra)
    return PinFacts(**base)


def page(rows, pin_facts=None, docs=(MAIN,), **extra):
    """A PinsMdInput over rows: loopback, frozen clock; facts default to facts() for every listed pin."""
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
        docs=docs,
        people={},
        now=NOW,
        updated="2026-09-26 10:00",
        token_file=None,
    )
    base.update(extra)
    return PinsMdInput(**base)


def table_row(text, pid):
    """The open table's row of pin pid in a rendered pins.md."""
    return next(line for line in text.splitlines() if line.startswith("| %d " % pid))


def number_cell(text, pid):
    """The number cell of pin pid's open-table row."""
    return table_row(text, pid).split(" | ")[0][2:]


class ContractStrings(unittest.TestCase):
    """The legend entry and the guidance clause are the spec's strings byte for byte."""

    def test_the_legend_entry_and_the_guidance_are_the_specs(self):
        """VERDICT_LEGEND is ' · ' + the spec's legend; the guidance is ' · ' + the spec's line with <base> filled."""
        self.assertEqual(VERDICT_LEGEND, " · " + SPEC_LEGEND)
        self.assertEqual(verdict_guidance("<base>"), " · " + SPEC_GUIDANCE)
        self.assertIn("GET http://127.0.0.1:18999/api/pins?all=1)", verdict_guidance("http://127.0.0.1:18999"))


class NumberCell(unittest.TestCase):
    """The marker '판정 <key>' leads the number cell; '(쪽 전체)' marks a whole page's target."""

    def test_the_marker_comes_right_after_the_number(self):
        """The spec's example: a whole-figure verdict pin claimed by an agent reads
        '41 · 판정 채택(쪽 전체) · 처리 중(에이전트 B, 약 10분)'; reopened, assigned and question markers follow it."""
        claim = {
            "claimed_by": {"login": "agent:b", "name": "에이전트 B"},
            "claim_until": NOW + 900,
            "eta_ts": NOW + 600,
        }
        text = pins_md_text(page([figure_row(verdict="채택", **claim)], {41: facts("fig")}, docs=(MAIN, FIG)))
        self.assertEqual(number_cell(text, 41), "41 · 판정 채택(쪽 전체) · 처리 중(에이전트 B, 약 10분)")
        busy = row(verdict="보류", kind_req="question", assignee="bob@example.com")
        text = pins_md_text(page([busy], {41: facts(reopened=True, addressed=("bob@example.com",))}))
        self.assertEqual(number_cell(text, 41), "41 · 판정 보류 · 다시 열림 · → @bob@example.com · 질문")

    def test_a_whole_page_target_is_a_figure_root_or_a_whole_pdf_page(self):
        """(쪽 전체) for a figure root on a figure document and for a whole-page region on a view-only PDF; not for a
        panel, a smaller region, a LaTeX pin with a whole-page box, or a pin whose document is not served."""
        cases = [
            (figure_row(verdict="채택"), "fig", "판정 채택(쪽 전체)"),
            (figure_row(verdict="채택", path=("B2", "B2/calendar")), "fig", "판정 채택"),
            (pdf_row(verdict="채택"), "rv", "판정 채택(쪽 전체)"),
            (pdf_row(verdict="채택", frac=(0, 0, 1, 0.5)), "rv", "판정 채택"),
            (row(verdict="채택", frac=[0, 0, 1, 1]), "main", "판정 채택"),
            (figure_row(verdict="채택"), "gone", "판정 채택"),
        ]
        for r, doc_key, marker in cases:
            with self.subTest(doc=doc_key, r=r):
                text = pins_md_text(page([r], {41: facts(doc_key)}, docs=(MAIN, FIG, RV)))
                self.assertEqual(number_cell(text, 41), "41 · " + marker)

    def test_a_stored_value_that_is_no_key_shows_nothing(self):
        """A number, a '|'-holding string or an over-long key stored as verdict is no verdict: no marker, no memo
        stand-in, no legend or guidance - the sheet reads as without the field."""
        plain = pins_md_text(page([row()]))
        for stored in (7, "a|b", "x" * 17, None):
            with self.subTest(stored=stored):
                self.assertEqual(pins_md_text(page([row(verdict=stored)])), plain)


class MemoCell(unittest.TestCase):
    """The memo cell of a verdict pin."""

    def test_an_empty_memo_says_the_verdict_is_the_whole_request(self):
        """An empty or blank memo reads (판정만); a memo is kept as it is."""
        for note, cell in (("", "(판정만)"), ("  ", "(판정만)"), ("이 그림은 본문으로", "이 그림은 본문으로")):
            with self.subTest(note=note):
                text = pins_md_text(page([row(verdict="채택", note=note)]))
                self.assertTrue(table_row(text, 41).endswith("| %s |" % cell), table_row(text, 41))

    def test_a_pin_without_a_verdict_keeps_an_empty_memo_empty(self):
        """(판정만) is for a verdict pin only."""
        text = pins_md_text(page([row()]))
        self.assertEqual(table_row(text, 41), "| 41 | 1 | `main.tex L4-L5` |  |  |")


class LegendAndGuidance(unittest.TestCase):
    """The legend entry and the guidance clause appear only while an open verdict pin is listed."""

    def lines(self, text):
        """(guidance paragraph, legend line) of a rendered pins.md."""
        lines = text.splitlines()
        guidance = next(line for line in lines if line.startswith("처리한 핀은 닫는다"))
        legend = next((line for line in lines if line.startswith("표시: ")), "")
        return guidance, legend

    def test_an_open_verdict_pin_adds_both_at_the_end(self):
        """The guidance paragraph ends with the clause on this base, the legend line with the entry."""
        guidance, legend = self.lines(pins_md_text(page([row(verdict="채택")])))
        self.assertTrue(guidance.endswith(verdict_guidance("http://127.0.0.1:18999")))
        self.assertEqual(legend, LEGEND + VERDICT_LEGEND)
        remote = pins_md_text(page([row(verdict="채택")], base="https://box.example.ts.net"))
        self.assertIn(verdict_guidance("https://box.example.ts.net"), self.lines(remote)[0])

    def test_the_verdict_entry_follows_the_suggestion_entry(self):
        """With a suggestion pin and a verdict pin open, the legend reads LEGEND, SUGGEST_LEGEND, VERDICT_LEGEND."""
        suggest = row(42, note="n", suggest={"base": "a", "text": "b"})
        text = pins_md_text(page([row(verdict="채택"), suggest], {41: facts(), 42: facts(suggest_state="ready")}))
        self.assertEqual(self.lines(text)[1], LEGEND + SUGGEST_LEGEND + VERDICT_LEGEND)

    def test_without_an_open_verdict_pin_no_byte_changes(self):
        """A verdict pin awaiting review or done adds nothing - not to the review table, nor to the legend an open
        question pin brings - and the sheet equals the one rendered without the field."""
        review = row(42, verdict="채택", done=True, review=True)
        done = row(43, verdict="보류", done=True)
        rows = [row(note="n", kind_req="question"), review, done]
        plain = [rows[0], *({k: v for k, v in r.items() if k != "verdict"} for r in (review, done))]
        got = pins_md_text(page(rows, {41: facts(), 42: facts()}))
        self.assertEqual(got, pins_md_text(page(plain, {41: facts(), 42: facts()})))
        self.assertNotIn("판정", got)


WORDS = {"format": "limn-verdicts/1", "page": True, "verdicts": [{"key": "채택"}, {"key": "보류"}]}


class OnDisk(AccessBase):
    """pins.md on disk after verdict pins made over HTTP in three documents: each document's subsection shows its
    pins' markers, and the legend and guidance follow while one is open."""

    def setUp(self):
        """ms (LaTeX), fig (figure, BUILD1 on screen) and rv (view-only PDF), each with the word file."""
        super().setUp()
        (self.src / "rv").mkdir()
        (self.src / "rv" / "review.pdf").write_bytes(MINI_PDF)
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        self.rv = Doc("rv", "답변", "pdf", self.src / "rv", self.src / "rv" / "review.pdf", paths=ps.APP.C.paths)
        self.ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        ps.APP.set_docs([self.ms, self.fig, self.rv])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, viewer_map(), pages=2)
        write_build(self.rv, BUILD1, None, pages=3)
        for doc in (self.ms, self.fig, self.rv):
            verdicts_path(doc).write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")

    def post(self, body):
        """Make a pin as editor Bob; its id."""
        code, d = self.call("POST", "/api/pin", body, headers=BOB)
        self.assertEqual(code, 200, d)
        return d["id"]

    def test_every_subsection_shows_its_verdict_pins(self):
        """A LaTeX verdict pin, a whole-figure one and a whole-page PDF one each lead their row in their document's
        subsection; the file ends its guidance and legend with the verdict entries; closing the last open one drops
        them again."""
        a = self.post({"doc": "ms", "file": str(self.main), "lo": 4, "hi": 5, "page": 1, "verdict": "채택"})
        el = {"id": "B2", "path": ["B2"]}
        b = self.post(
            {"doc": "fig", "file": SCRIPT, "lo": 12, "hi": 140, "page": 1, "el": el, "verdict": "보류", "note": "x"}
        )
        c = self.post({"doc": "rv", "page": 2, "frac": [0, 0, 1, 1], "verdict": "채택", "pdf_build": BUILD1})
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        sections = text.split("\n## ")
        by_doc = {
            key: next(s for s in sections if s.startswith(title))
            for key, title in (("ms", "본문 · `ms`"), ("fig", "그림 · `fig`"), ("rv", "답변 · `rv`"))
        }
        self.assertIn("| %d · 판정 채택 | 1 |" % a, by_doc["ms"])
        self.assertTrue(table_row(text, a).endswith("| (판정만) |"))
        self.assertIn("| %d · 판정 보류(쪽 전체) | 1 |" % b, by_doc["fig"])
        self.assertIn("| %d · 판정 채택(쪽 전체) | 2 |" % c, by_doc["rv"])
        self.assertIn(VERDICT_LEGEND, text)
        self.assertIn(verdict_guidance("http://127.0.0.1:18999"), text)
        for pid in (a, b, c):
            self.assertEqual(self.call("POST", "/api/pins/%d/close" % pid, {})[0], 200)
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("판정", text)

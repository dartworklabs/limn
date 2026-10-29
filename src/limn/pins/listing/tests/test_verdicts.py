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
    VERDICT_SUPERSEDED_GUIDANCE,
    VERDICT_SUPERSEDED_LEGEND,
    DocHeading,
    PinFacts,
    PinsMdInput,
    josa_ro,
    pins_md_text,
    superseded_marker,
    verdict_guidance,
)
from limn.runtime.documents import Doc

from helpers import MINI_PDF, ps
from helpers_access import BOB, AccessBase
from helpers_figure import BUILD1, BUILD2, SCRIPT, figure_doc, viewer_map, write_build

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
        self.assertTrue(VERDICT_SUPERSEDED_LEGEND.startswith(" · '#N로 대체됨' = "))
        self.assertTrue(VERDICT_SUPERSEDED_GUIDANCE.startswith(" · '판정 X' 다음에 '#N로 대체됨'이 붙은 판정 핀은 "))
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


class SupersededMarker(unittest.TestCase):
    """A verdict pin that a newer verdict pin supersedes says so in the number cell, right after '판정 <key>' (ADR-0023)."""

    def test_the_particle_follows_the_last_syllable_spoken(self):
        """'으로' after 영, 삼, 육 and after 십·백·천; at the end of a group of four digits after the unit's name: 만, 억,
        경, 양, 간, 정, 극 take '으로', 조, 해, 자, 구, 재 take '로' (10**12, 일조, is '로' though it ends in 0)."""
        by_digit = {d: josa_ro(d) for d in range(10)}
        self.assertEqual(
            by_digit, {0: "으로", 1: "로", 2: "로", 3: "으로", 4: "로", 5: "로", 6: "으로", 7: "로", 8: "로", 9: "로"}
        )
        cases = {
            10: "으로",
            12: "로",
            16: "으로",
            17: "로",
            20: "으로",
            100: "으로",
            101: "로",
            1000: "으로",
            1010: "으로",
            9999: "로",
            10**4: "으로",  # 만
            2 * 10**4: "으로",
            10**5: "으로",  # 십만
            12 * 10**4: "으로",
            10**8: "으로",  # 억
            10**9: "으로",  # 십억
            10**12: "로",  # 조
            3 * 10**12: "로",
            10**13: "로",  # 십조
            10**14: "로",  # 백조
            10**12 + 10**4: "으로",  # 일조 일만
            10**12 + 5: "로",  # 일조 오
            10**16: "으로",  # 경
            10**20: "로",  # 해
            10**24: "로",  # 자
            10**28: "으로",  # 양
            10**32: "로",  # 구
        }
        for n, want in cases.items():
            with self.subTest(n=n):
                self.assertEqual(josa_ro(n), want)
                self.assertEqual(superseded_marker(n), "#%d%s 대체됨" % (n, want))

    def test_the_marker_follows_the_verdict_marker_before_the_others(self):
        """'41 · 판정 보류 · #16으로 대체됨', and with a whole-page target and a claim after both."""
        text = pins_md_text(page([row(verdict="보류")], {41: facts(superseded_by=16)}))
        self.assertEqual(number_cell(text, 41), "41 · 판정 보류 · #16으로 대체됨")
        claim = {
            "claimed_by": {"login": "agent:b", "name": "에이전트 B"},
            "claim_until": NOW + 900,
            "eta_ts": NOW + 600,
        }
        text = pins_md_text(
            page(
                [figure_row(verdict="채택", **claim)],
                {41: facts("fig", superseded_by=43, reopened=True)},
                docs=(MAIN, FIG),
            )
        )
        self.assertEqual(
            number_cell(text, 41), "41 · 판정 채택(쪽 전체) · #43으로 대체됨 · 다시 열림 · 처리 중(에이전트 B, 약 10분)"
        )

    def test_a_pin_without_a_verdict_never_shows_it(self):
        """The marker belongs to a verdict: facts that name a superseder for an ordinary pin, or for a stored value
        that is no key, change nothing."""
        plain = pins_md_text(page([row(note="n")]))
        self.assertEqual(pins_md_text(page([row(note="n")], {41: facts(superseded_by=9)})), plain)
        no_key = pins_md_text(page([row(note="n", verdict=7)], {41: facts(superseded_by=9)}))
        self.assertEqual(no_key, plain)

    def test_the_review_table_shows_no_marker(self):
        """A superseded verdict pin awaiting review is not worked: its row in the review table is as it was, and the
        sheet gains no legend entry or guidance clause for it."""
        review = row(42, verdict="채택", done=True, review=True)
        with_fact = pins_md_text(page([row(note="n"), review], {41: facts(), 42: facts(superseded_by=44)}))
        without = pins_md_text(page([row(note="n"), review], {41: facts(), 42: facts()}))
        self.assertEqual(with_fact, without)
        self.assertNotIn("대체됨", with_fact)


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

    def test_a_superseded_pin_adds_its_own_entry_and_clause_after_the_verdict_ones(self):
        """Only while an open superseded verdict pin is listed: the guidance ends with VERDICT_SUPERSEDED_GUIDANCE after
        the verdict clause, the legend with VERDICT_SUPERSEDED_LEGEND after the verdict entry. Everything else in the sheet
        is what it is without the fact."""
        current = row(42, verdict="보류")
        old = row(41, verdict="채택")
        sheet = page([old, current], {41: facts(superseded_by=42), 42: facts()})
        text = pins_md_text(sheet)
        guidance, legend = self.lines(text)
        self.assertTrue(guidance.endswith(verdict_guidance("http://127.0.0.1:18999") + VERDICT_SUPERSEDED_GUIDANCE))
        self.assertEqual(legend, LEGEND + VERDICT_LEGEND + VERDICT_SUPERSEDED_LEGEND)
        plain = pins_md_text(page([old, current], {41: facts(), 42: facts()}))
        extra = {
            "| 41 · 판정 채택 · #42로 대체됨 |": "| 41 · 판정 채택 |",
            VERDICT_SUPERSEDED_GUIDANCE: "",
            VERDICT_SUPERSEDED_LEGEND: "",
        }
        for new, old_text in extra.items():
            text = text.replace(new, old_text)
        self.assertEqual(text, plain)

    def test_the_current_verdict_alone_adds_neither(self):
        """Verdict pins that supersede and are not superseded themselves leave the sheet with the verdict entries only."""
        guidance, legend = self.lines(pins_md_text(page([row(42, verdict="보류")], {42: facts()})))
        self.assertNotIn(VERDICT_SUPERSEDED_GUIDANCE, guidance)
        self.assertEqual(legend, LEGEND + VERDICT_LEGEND)

    def test_the_clauses_follow_the_suggestion_entry_too(self):
        """With a suggestion pin open as well, the legend reads LEGEND, SUGGEST_LEGEND, VERDICT_LEGEND, then the superseded entry."""
        suggest = row(43, note="n", suggest={"base": "a", "text": "b"})
        sheet = page(
            [row(41, verdict="채택"), row(42, verdict="보류"), suggest],
            {41: facts(superseded_by=42), 42: facts(), 43: facts(suggest_state="ready")},
        )
        self.assertEqual(
            self.lines(pins_md_text(sheet))[1], LEGEND + SUGGEST_LEGEND + VERDICT_LEGEND + VERDICT_SUPERSEDED_LEGEND
        )

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

    def test_a_whole_page_target_does_not_depend_on_the_word_files_page(self):
        """page asks a client to offer per-page verdicts and is answered as verdicts.page; it does not decide which
        verdict pins the server takes. With page false (the default), a whole-figure verdict pin and a whole-page PDF
        one are still made and still marked (쪽 전체), while the documents answer verdicts.page false."""
        for doc in (self.fig, self.rv):
            verdicts_path(doc).write_text(json.dumps(dict(WORDS, page=False), ensure_ascii=False), encoding="utf-8")
        _, docs = self.call("GET", "/api/docs", headers=BOB)
        pages = {d["key"]: d["verdicts"]["page"] for d in docs["docs"] if d["key"] in ("fig", "rv")}
        self.assertEqual(pages, {"fig": False, "rv": False})
        el = {"id": "B2", "path": ["B2"]}
        b = self.post({"doc": "fig", "page": 1, "frac": [0, 0, 1, 1], "el": el, "verdict": "보류", "pdf_build": BUILD1})
        c = self.post({"doc": "rv", "page": 2, "frac": [0, 0, 1, 1], "verdict": "채택", "pdf_build": BUILD1})
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertTrue(table_row(text, b).startswith("| %d · 판정 보류(쪽 전체) |" % b))
        self.assertTrue(table_row(text, c).startswith("| %d · 판정 채택(쪽 전체) |" % c))


ALICE_H = {"Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice Kim"}
ROOT_EL = {"id": "B2", "path": ["B2"]}
PANEL_EL = {"id": "B2/calendar", "path": ["B2", "B2/calendar"]}


class SupersededOverHTTP(OnDisk):
    """The supersession (ADR-0023) in what agents read: GET /api/pins (open pins), ?all=1, GET /api/pins/{id}, and
    pins.md on disk and from GET /pins.md - for verdicts made by two people in each kind of document."""

    def setUp(self):
        """OnDisk's three documents with their word files, and main.tex as the LaTeX document."""
        super().setUp()
        self.main_body = {"doc": "ms", "file": str(self.main), "page": 1}

    def make(self, body, who=BOB):
        """Make a pin as person who; its id."""
        code, d = self.call("POST", "/api/pin", body, headers=who)
        self.assertEqual(code, 200, d)
        return d["id"]

    def figure(self, verdict, el=ROOT_EL, who=BOB):
        """A figure verdict on the element el of fig's first page."""
        return self.make(
            {
                "doc": "fig",
                "file": SCRIPT,
                "lo": 12,
                "hi": 140,
                "page": 1,
                "el": el,
                "verdict": verdict,
                "pdf_build": BUILD1,
            },
            who,
        )

    def lines(self, verdict, lo=4, hi=5, who=BOB):
        """A LaTeX verdict on lines lo-hi of main.tex."""
        return self.make({**self.main_body, "lo": lo, "hi": hi, "verdict": verdict}, who)

    def page(self, verdict, page=2, frac=(0, 0, 1, 1), who=BOB):
        """A view-only PDF verdict over frac of page."""
        return self.make({"doc": "rv", "page": page, "frac": list(frac), "verdict": verdict, "pdf_build": BUILD1}, who)

    def listed(self, query="?all=1"):
        """{id: pin} of GET /api/pins<query>."""
        code, d = self.call("GET", "/api/pins" + query, headers=BOB)
        self.assertEqual(code, 200, d)
        return {p["id"]: p for p in d}

    def superseded(self, query="?all=1"):
        """{id: superseded_by} of the pins that have the field in GET /api/pins<query>."""
        return {i: p["superseded_by"] for i, p in self.listed(query).items() if "superseded_by" in p}

    def row(self, pid, text=None):
        """The open-table row of pin pid in pins.md on disk (or in text)."""
        return table_row(text if text is not None else ps.APP.C.pins_md.read_text(encoding="utf-8"), pid)

    def cell(self, pid, text=None):
        """The number cell of pin pid in pins.md on disk (or in text)."""
        return number_cell(text if text is not None else ps.APP.C.pins_md.read_text(encoding="utf-8"), pid)

    def test_a_figure_verdict_names_the_newest_verdict_of_its_figure(self):
        """ADR-0022 D1: a verdict on the figure and one on a panel of it are one target. The older names the newer in
        every answer, and the newer has no field; two people, and the newer on a panel (no '(쪽 전체)')."""
        first = self.figure("보류", who=ALICE_H)
        second = self.figure("채택", PANEL_EL, who=BOB)
        self.assertEqual(self.superseded(), {first: second})
        self.assertEqual(self.superseded(""), {first: second})
        code, d = self.call("GET", "/api/pins/%d" % first, headers=BOB)
        self.assertEqual((code, d["pin"]["superseded_by"]), (200, second))
        self.assertNotIn("superseded_by", self.call("GET", "/api/pins/%d" % second, headers=BOB)[1]["pin"])
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertEqual(
            self.cell(first, text), "%d · 판정 보류(쪽 전체) · #%d로 대체됨 · #%d와 같은 범위" % (first, second, second)
        )
        self.assertEqual(self.cell(second, text), "%d · 판정 채택 · #%d과 같은 범위" % (second, first))
        self.assertEqual(self.call("GET", "/pins.md")[1].count("대체됨"), text.count("대체됨"))
        self.assertIn(VERDICT_SUPERSEDED_LEGEND, text)
        self.assertIn(VERDICT_SUPERSEDED_GUIDANCE, text)

    def test_the_current_verdict_is_named_not_the_next_newer_one(self):
        """With three verdicts on a figure, the first two both name the third."""
        a, b, c = self.figure("보류"), self.figure("채택", PANEL_EL), self.figure("보류", ALICE_H and ROOT_EL, ALICE_H)
        self.assertEqual(self.superseded(), {a: c, b: c})

    def test_a_deleted_newer_verdict_supersedes_nothing_and_a_restored_one_does_again(self):
        """Dropping the newest verdict makes the one before it current again, in the API and in pins.md; restoring the pin
        puts the field and the marker back. The legend and guidance clause follow the marker."""
        first, second = self.figure("보류"), self.figure("채택")
        self.assertEqual(self.superseded(), {first: second})
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % second, {}, headers=BOB)[0], 200)
        self.assertEqual(self.superseded(), {})
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertEqual(self.cell(first, text), "%d · 판정 보류(쪽 전체)" % first)
        self.assertNotIn("대체됨", text)
        self.assertEqual(self.call("POST", "/api/pins/%d/restore" % second, {}, headers=BOB)[0], 200)
        self.assertEqual(self.superseded(), {first: second})
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertEqual(
            self.cell(first, text), "%d · 판정 보류(쪽 전체) · #%d로 대체됨 · #%d와 같은 범위" % (first, second, second)
        )
        self.assertIn(VERDICT_SUPERSEDED_LEGEND, text)

    def test_deleting_the_older_verdict_leaves_the_newer_one_current(self):
        """The older pin in the Trash has no field to show, and the newer one never had one."""
        first, second = self.figure("보류"), self.figure("채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % first, {}, headers=BOB)[0], 200)
        self.assertEqual(self.superseded(), {})
        self.assertIn(second, self.listed())

    def test_a_closed_newer_verdict_supersedes_an_open_one(self):
        """The newest verdict stays current whatever its state (ADR-0021 D4): an agent's close sends it to review, the
        older open verdict is still superseded, and the default list - open pins - tells it so."""
        first, second = self.figure("보류"), self.figure("채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % second, {})[0], 200)
        self.assertEqual(self.listed("")[first]["superseded_by"], second)
        self.assertNotIn(second, self.listed(""))
        self.assertIn("#%d로 대체됨" % second, self.cell(first))

    def test_a_reopened_verdict_does_not_change_the_order(self):
        """Closing and reopening a pin leaves the order to the numbers (ADR-0021 D4)."""
        first, second = self.figure("보류"), self.figure("채택")
        self.call("POST", "/api/pins/%d/close" % first, {})
        self.assertEqual(self.superseded(), {first: second})
        code, d = self.call("POST", "/api/pins/%d/reopen" % first, {"reason": "again"}, headers=BOB)
        self.assertEqual(code, 200, d)
        self.assertEqual(self.superseded(), {first: second})

    def test_a_pin_without_a_verdict_or_a_newer_verdict_has_no_field(self):
        """An ordinary pin on the same figure, and the only verdict of a figure, have none."""
        only = self.figure("보류")
        ordinary = self.make({"doc": "fig", "file": SCRIPT, "lo": 12, "hi": 140, "page": 1, "el": ROOT_EL, "note": "n"})
        self.assertEqual(self.superseded(), {})
        self.assertTrue(self.cell(only).startswith("%d · 판정 보류(쪽 전체)" % only), self.cell(only))
        self.assertNotIn("대체됨", ps.APP.C.pins_md.read_text(encoding="utf-8"))
        self.assertIn(ordinary, self.listed())

    def test_latex_verdicts_on_the_same_lines_supersede(self):
        """Two open verdicts on lines 4-5 of main.tex: the newer supersedes the older. Other lines are another target,
        and a closed older verdict on the same text is superseded by a newer open one."""
        first, other, second = self.lines("채택"), self.lines("채택", 8, 9), self.lines("보류")
        self.assertEqual(self.superseded(), {first: second})
        self.assertNotIn(other, self.superseded())
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % second, {})[0], 200)
        third = self.lines("채택")
        self.assertEqual(self.superseded(), {first: third, second: third})
        self.assertIn("#%d로 대체됨" % third, self.cell(first))

    def test_view_only_page_verdicts_supersede_per_page(self):
        """Whole-page verdicts on page 2 supersede each other; page 3 and a region of page 2 are other targets."""
        first, elsewhere, part, second = (
            self.page("채택"),
            self.page("채택", 3),
            self.page("채택", frac=(0, 0, 1, 0.5)),
            self.page("보류"),
        )
        self.assertEqual(self.superseded(), {first: second})
        self.assertEqual(self.cell(first), "%d · 판정 채택(쪽 전체) · #%d로 대체됨" % (first, second))
        self.assertNotIn(elsewhere, self.superseded())
        self.assertNotIn(part, self.superseded())

    def test_each_document_is_its_own_order(self):
        """Verdicts of different documents never supersede each other, even with the same page or figure."""
        fig, pdf, tex = self.figure("보류"), self.page("보류", 1), self.lines("보류")
        self.assertEqual(self.superseded(), {})
        self.assertEqual({fig, pdf, tex} - set(self.listed()), set())

    def test_an_instance_without_a_superseded_verdict_prints_its_sheet_as_before(self):
        """A sheet of current verdicts equals the one rendered without any supersession logic: no marker, no extra clause."""
        self.figure("보류")
        self.lines("채택")
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("대체됨", text)
        self.assertNotIn(VERDICT_SUPERSEDED_GUIDANCE, text)
        self.assertNotIn(VERDICT_SUPERSEDED_LEGEND, text)

    def test_a_pin_of_an_unserved_document_has_no_target(self):
        """If the instance serves the document no more, its verdict pins are not placed: no pin of it has the field."""
        a, b = self.figure("보류"), self.figure("채택")
        self.assertEqual(self.superseded(), {a: b})
        ps.APP.set_docs([self.ms, self.rv])
        self.assertEqual(self.superseded(), {})

    def test_a_pdf_verdict_whose_mark_is_only_an_estimate_is_left_out(self):
        """The viewer drops a whole-page pin whose mark is only an estimate on the PDF on screen (est) from the order, and
        the server does the same: after the PDF is replaced, the verdicts made on the old one neither supersede nor are
        superseded, while two made on the new one do."""
        old_a, old_b = self.page("채택"), self.page("보류")
        self.assertEqual(self.superseded(), {old_a: old_b})
        write_build(self.rv, BUILD2, None, pages=3)
        listed = self.listed()
        self.assertEqual({listed[old_a]["est"], listed[old_b]["est"]}, {True})
        self.assertEqual(self.superseded(), {})
        self.assertNotIn("대체됨", self.call("GET", "/pins.md")[1])
        new_a = self.make({"doc": "rv", "page": 2, "frac": [0, 0, 1, 1], "verdict": "채택", "pdf_build": BUILD2})
        new_b = self.make({"doc": "rv", "page": 2, "frac": [0, 0, 1, 1], "verdict": "보류", "pdf_build": BUILD2})
        self.assertEqual(self.superseded(), {new_a: new_b})

    def test_a_first_word_verdict_is_not_read_so_the_named_pin_may_not_be_the_current_verdict(self):
        """Explicit #1 and #2 and a pin of the older form (no `verdict`, its memo starts with a verdict word) as #3: the
        server never reads memos (ADR-0021 D1), so it answers {1: 2} and neither #2 nor #3 has the field, although an agent
        that counts both forms (SKILL step 1) takes #3 as the current verdict. The named pin is the newest explicit one,
        and pins.md marks only #1. Same on a LaTeX document's lines."""
        first, second = self.figure("보류"), self.figure("채택")
        old_form = self.make(
            {"doc": "fig", "file": SCRIPT, "lo": 12, "hi": 140, "page": 1, "el": ROOT_EL, "note": "보류 옛 꼴"}
        )
        self.assertEqual(self.superseded(), {first: second})
        self.assertNotIn("verdict", self.listed()[old_form])
        text = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("#%d로 대체됨" % second, self.cell(first, text))
        self.assertNotIn("대체됨", self.cell(second, text))
        self.assertNotIn("대체됨", self.cell(old_form, text))
        self.assertNotIn("판정", self.cell(old_form, text))
        lines_a, lines_b = self.lines("채택"), self.lines("보류")
        old_lines = self.make({**self.main_body, "lo": 4, "hi": 5, "note": "채택 옛 꼴"})
        self.assertEqual(self.superseded(), {first: second, lines_a: lines_b})
        self.assertNotIn(old_lines, self.superseded())

"""Suggested edits in what agents read (docs/adr/0020-suggested-edit-pins.md D3): the pins.md marker, memo cell,
`## 제안 문안` section, guidance clause and legend entry from the pure renderer (limn.pins.listing.render), then the
same through the server - GET /pins.md, the file on disk and GET /api/pins.

Run: uv run pytest -q src/limn/pins/listing/tests/test_suggestions.py
"""

import json
import re
import unittest

from hypothesis import given, strategies as st

from limn.pins.listing.render import (
    LEGEND,
    SUGGEST_GUIDANCE,
    SUGGEST_LEGEND,
    DocHeading,
    PinFacts,
    PinsMdInput,
    code_fence,
    pins_md_text,
)

from helpers import Base, jreq, ps, req, split_resp
from helpers_access import ALICE, TS_HOST

MAIN = DocHeading("main", "본문", "main.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
RV = DocHeading("rv", "리뷰", "review.pdf", view_only=True, builds_from_source=False, head=None, built_at=None)
SUGGEST = {"base": "Old line one.\nOld line two.", "text": "New line one.\nNew line two."}


def row(pid=7, **extra):
    """An open line pin on main.tex L120-L123 with a note, and whatever else is given."""
    return {"id": pid, "file": "/ms/main.tex", "lo": 120, "hi": 123, "page": 3, "note": "왜 바꾸는지", **extra}


def facts(**extra):
    """PinFacts of a plain line pin in the first document at main.tex, nothing else decided about it."""
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
        now=1_790_000_000.0,
        updated="2026-09-26 10:00",
        token_file=None,
    )
    base.update(extra)
    return PinsMdInput(**base)


def table_row(text, pid):
    """The open table's row of pin pid in a rendered pins.md."""
    return next(line for line in text.splitlines() if line.startswith("| %d" % pid))


def section(text):
    """The `## 제안 문안` section's lines, up to the next level-two heading or the end."""
    lines = text.splitlines()
    start = lines.index("## 제안 문안")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


class Unchanged(unittest.TestCase):
    """Without an open pin carrying a suggestion, pins.md is what it was."""

    def test_a_suggestion_on_a_pin_awaiting_review_changes_no_byte(self):
        """An open pin without one and a review pin with one render exactly as with no suggestion at all."""
        review = row(8, done=True, review=True, suggest=SUGGEST)
        rows = [row(), review]
        plain = [row(), {k: v for k, v in review.items() if k != "suggest"}]
        got = pins_md_text(page(rows, {7: facts(), 8: facts(suggest_state="ready")}))
        self.assertEqual(got, pins_md_text(page(plain, {7: facts(), 8: facts()})))
        self.assertNotIn("제안", got)


class Markers(unittest.TestCase):
    """The number-cell marker and the memo cell of a pin with a suggestion."""

    def test_the_marker_names_the_state(self):
        """ready, changed and unknown read 제안 수정, 제안 수정(원문 바뀜), 제안 수정(확인 불가); a state the edge did not
        give reads as unknown."""
        for state, marker in (
            ("ready", "제안 수정"),
            ("changed", "제안 수정(원문 바뀜)"),
            ("unknown", "제안 수정(확인 불가)"),
            (None, "제안 수정(확인 불가)"),
        ):
            with self.subTest(state=state):
                text = pins_md_text(page([row(suggest=SUGGEST)], {7: facts(suggest_state=state)}))
                self.assertTrue(table_row(text, 7).startswith("| 7 · %s |" % marker))

    def test_the_marker_comes_after_every_other_marker(self):
        """With 수정됨 and 위치 잃음 on the same pin, the suggestion's marker is the last one of the cell."""
        r = row(suggest=SUGGEST, edited_at="2026-09-26 09:00", stale=True)
        text = pins_md_text(page([r], {7: facts(suggest_state="unknown")}))
        self.assertTrue(table_row(text, 7).startswith("| 7 · 수정됨 · 위치 잃음 · 제안 수정(확인 불가) |"))

    def test_an_empty_memo_says_the_suggestion_is_the_whole_request(self):
        """An empty or blank memo reads (제안 문안만); a memo is kept as it is."""
        for note, cell in (("", "(제안 문안만)"), ("  ", "(제안 문안만)"), ("왜 바꾸는지", "왜 바꾸는지")):
            with self.subTest(note=note):
                text = pins_md_text(page([row(note=note, suggest=SUGGEST)], {7: facts(suggest_state="ready")}))
                self.assertTrue(table_row(text, 7).endswith("| %s |" % cell), table_row(text, 7))

    def test_a_pin_without_a_suggestion_keeps_an_empty_memo_empty(self):
        """(제안 문안만) is for a suggestion pin only."""
        text = pins_md_text(page([row(note="")]))
        self.assertEqual(table_row(text, 7), "| 7 | 3 | `main.tex L120-L123` |  |  |")
        self.assertNotIn("제안 문안만", text)


class Section(unittest.TestCase):
    """The `## 제안 문안` section: where it stands and what each block holds."""

    def test_it_follows_the_open_table_and_precedes_the_review_section(self):
        """Table rows, then the section, then ## 검토 대기."""
        rows = [row(suggest=SUGGEST), row(9, done=True, review=True)]
        text = pins_md_text(page(rows, {7: facts(suggest_state="ready"), 9: facts()}))
        lines = text.splitlines()
        self.assertLess(lines.index(table_row(text, 7)), lines.index("## 제안 문안"))
        review = next(i for i, line in enumerate(lines) if line.startswith("## 검토 대기"))
        self.assertLess(lines.index("## 제안 문안"), review)

    def test_each_block_is_a_heading_and_the_text_in_a_fence(self):
        """The section names JSON as the authority with the loopback base, then per pin by id the heading with the
        location and the state's words, and the text line by line in a three-backtick fence."""
        rows = [row(9, suggest={"base": "a", "text": "b"}), row(suggest=SUGGEST)]
        text = pins_md_text(page(rows, {7: facts(suggest_state="ready"), 9: facts(suggest_state="changed")}))
        self.assertEqual(
            section(text),
            [
                "## 제안 문안",
                "",
                "정확한 바이트의 정본은 GET http://127.0.0.1:18999/api/pins/N 의 suggest.text 다. 아래 블록은 같은 글이다.",
                "",
                "### #7 · main.tex L120-L123 · 바꿀 준비됨",
                "```",
                "New line one.",
                "New line two.",
                "```",
                "",
                "### #9 · main.tex L120-L123 · 원문 바뀜 — 넣지 않는다",
                "```",
                "b",
                "```",
            ],
        )

    def test_an_unknown_state_and_an_empty_text(self):
        """unknown says 확인 불가 — 넣지 않는다; an empty text says the range is deleted instead of a block."""
        text = pins_md_text(page([row(suggest={"base": "a", "text": ""})], {7: facts(suggest_state="unknown")}))
        self.assertEqual(
            section(text)[-2:], ["### #7 · main.tex L120-L123 · 확인 불가 — 넣지 않는다", "(이 줄 범위를 지운다)"]
        )

    def test_the_fence_is_one_backtick_longer_than_the_longest_run(self):
        """No backtick, or runs of one and two: three; a run of three: four; a run of five: six."""
        for content, fence in (
            ("plain", "```"),
            ("`a` and ``b``", "```"),
            ("```\ncode\n```", "````"),
            ("x`````y", "``````"),
        ):
            with self.subTest(content=content):
                self.assertEqual(code_fence(content), fence)

    @given(st.text(alphabet=st.characters(blacklist_characters="\r", blacklist_categories=("Cs",)), min_size=1))
    def test_the_block_holds_any_text_exactly(self, content):
        """For any text without a CR, the lines between the block's fences joined with newlines are the text, and no
        line inside can close the fence."""
        text = pins_md_text(
            page([row(suggest={"base": content + "x", "text": content})], {7: facts(suggest_state="ready")})
        )
        lines = text.splitlines()
        heading = lines.index("### #7 · main.tex L120-L123 · 바꿀 준비됨")
        fence = lines[heading + 1]
        self.assertTrue(set(fence) == {"`"} and len(fence) >= 3)
        body = text.split("\n### #7 · main.tex L120-L123 · 바꿀 준비됨\n" + fence + "\n", 1)[1]
        self.assertEqual(body.split("\n" + fence + "\n", 1)[0], content)
        self.assertFalse(any(re.match("`{%d,}" % len(fence), part) for part in content.split("\n")))

    def test_a_sheet_of_several_documents_names_the_document(self):
        """In a sectioned pins.md the heading starts with the document key, as the review table's location does."""
        text = pins_md_text(page([row(suggest=SUGGEST)], {7: facts(suggest_state="ready")}, docs=(MAIN, RV)))
        self.assertIn("### #7 · `main` · main.tex L120-L123 · 바꿀 준비됨", text)

    def test_a_remote_reader_gets_its_own_base(self):
        """GET /pins.md through another host names that base in the section's authority line."""
        base = "https://box.example.ts.net:8443"
        text = pins_md_text(page([row(suggest=SUGGEST)], {7: facts(suggest_state="ready")}, base=base))
        self.assertIn("정확한 바이트의 정본은 GET %s/api/pins/N 의 suggest.text 다." % base, text)


class Guidance(unittest.TestCase):
    """The guidance clause and the legend entry exist only while an open pin carries a suggestion."""

    def test_the_guidance_gains_its_clause_and_the_legend_its_entry(self):
        """The contract line ends the guidance paragraph and the 제안 수정 entry ends the legend; without such a pin
        neither appears, and the legend is the one it always was."""
        with_one = pins_md_text(page([row(suggest=SUGGEST)], {7: facts(suggest_state="ready")})).splitlines()
        guidance = next(line for line in with_one if line.startswith("처리한 핀은 닫는다"))
        self.assertTrue(guidance.endswith(SUGGEST_GUIDANCE))
        self.assertIn(
            "제안 수정 핀은 메모를 다시 쓰지 말고 `suggest.text` 를 위치 칸의 줄 범위에 글자 그대로 넣는다 · "
            "`원문 바뀜`·`확인 불가` 면 넣지 말고 답글로 알린다",
            guidance,
        )
        self.assertIn(LEGEND + SUGGEST_LEGEND, with_one)
        without = pins_md_text(page([row(edited_at="2026-09-26 09:00")])).splitlines()
        self.assertIn(LEGEND, without)
        self.assertFalse(any("제안 수정" in line for line in without))


class SuggestionsThroughTheServer(Base):
    """A stored suggestion as GET /pins.md, the pins.md file on disk and GET /api/pins show it."""

    def suggested_pin(self):
        """A pin on main.tex lines 4-5 whose suggestion was set through POST /api/pins/{id}/edit; its id."""
        pid = self.add(note="")
        body = {
            "base_rev": 0,
            "suggest": {
                "base": "First paragraph line one about rarewordalpha.\nFirst paragraph line two.",
                "text": "One ``tick`` line.",
            },
        }
        code, _, out = split_resp(self.talk(jreq("POST", "/api/pins/%d/edit" % pid, body)))
        self.assertEqual(code, 200, out)
        return pid

    def test_pins_md_over_http_and_on_disk_carry_the_marker_and_the_block(self):
        """GET /pins.md through the tailnet host (with a person's identity, as tailscale serve sends it) names that
        base; the file on disk names loopback; both carry the ready marker after 수정됨 (the suggestion was set by an
        edit), (제안 문안만) and the text in its fence."""
        pid = self.suggested_pin()
        code, _, out = split_resp(
            self.talk(req("GET", "/pins.md", headers={"Host": TS_HOST, **ALICE, "X-Forwarded-For": "100.64.0.9"}))
        )
        self.assertEqual(code, 200, out)
        remote = out.decode("utf-8")
        disk = ps.APP.C.state.joinpath("pins.md").read_text(encoding="utf-8")
        self.assertIn("GET https://%s/api/pins/N" % TS_HOST, remote)
        self.assertIn("GET http://127.0.0.1:", disk)
        for text in (remote, disk):
            with self.subTest(remote=text is remote):
                self.assertTrue(table_row(text, pid).startswith("| %d · 수정됨 · 제안 수정 |" % pid))
                self.assertIn("(제안 문안만)", table_row(text, pid))
                self.assertIn("### #%d · main.tex L4-L5 · 바꿀 준비됨\n```\nOne ``tick`` line.\n```\n" % pid, text)

    def test_the_marker_follows_the_file(self):
        """After the paragraph is edited, GET /pins.md marks the pin 원문 바뀜 and its block 넣지 않는다."""
        pid = self.suggested_pin()
        self.main.write_text(
            self.main.read_text(encoding="utf-8").replace("First paragraph line two.", "Line two, edited."),
            encoding="utf-8",
        )
        code, _, out = split_resp(self.talk(req("GET", "/pins.md")))
        text = out.decode("utf-8")
        self.assertTrue(table_row(text, pid).startswith("| %d · 수정됨 · 제안 수정(원문 바뀜) |" % pid))
        self.assertIn("### #%d · main.tex L4-L5 · 원문 바뀜 — 넣지 않는다" % pid, text)

    def test_the_list_answers_the_state_last(self):
        """GET /api/pins: the suggestion's pin ends with suggest_state; a pin without one has no such field."""
        pid = self.suggested_pin()
        other = self.add(lo=8, hi=9)
        code, _, out = split_resp(self.talk(req("GET", "/api/pins")))
        pins = {p["id"]: p for p in json.loads(out)}
        self.assertEqual((list(pins[pid])[-1], pins[pid]["suggest_state"]), ("suggest_state", "ready"))
        self.assertNotIn("suggest_state", pins[other])

    def test_the_trash_does_not_answer_a_state(self):
        """A dropped pin keeps its suggestion in the Trash, without a computed suggest_state."""
        pid = self.suggested_pin()
        code, _, out = split_resp(self.talk(jreq("POST", "/api/pins/%d/drop" % pid, {})))
        self.assertEqual(code, 200, out)
        code, _, out = split_resp(self.talk(req("GET", "/api/pins/dropped")))
        entry = next(p for p in json.loads(out)["dropped"] if p["id"] == pid)
        self.assertIn("suggest", entry)
        self.assertNotIn("suggest_state", entry)

    def test_change_responses_answer_the_state_too(self):
        """The pin of a claim's and a close's answer carries suggest_state as its last field, like GET's."""
        pid = self.suggested_pin()
        for action, body in (("claim", {"eta_min": 5}), ("close", {})):
            with self.subTest(action=action):
                code, _, out = split_resp(self.talk(jreq("POST", "/api/pins/%d/%s" % (pid, action), body)))
                self.assertEqual(code, 200, out)
                pin = json.loads(out)["pin"]
                self.assertEqual((list(pin)[-1], pin["suggest_state"]), ("suggest_state", "ready"))

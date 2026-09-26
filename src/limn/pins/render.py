"""pins.md rendering: the agents' work list as text, from one explicit input.

pins.md is an agent contract (docs/handbook/api.md §pins.md): its columns, markers and Korean header lines are read
by agents in other repositories, so the bytes this module produces must only ever grow. Everything here is pure.
What the text needs from outside the records - the run settings, the documents and their build stamps, the clock,
this machine's token file, and what other parts decide about each pin (where its file is, its overlap badge, who it
is addressed to, its current thread round) - arrives as values in PinsMdInput, built by server.pins_md_input().
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeGuard

from limn.guidance import token_file_curl
from limn.mapping import truncate_quote
from limn.pins.lifecycle import claim_holds
from limn.pins.model import Record, ReviewPin, is_region_pin, parse_pin


@dataclass(frozen=True)
class DocHeading:
    """One configured document as pins.md names it, with its build stamp as read from its build folder.

    head is the short git hash the page images came from ('-' outside git) and built_at when they were committed;
    either is None when the document was never built. path is the main file relative to --manuscript."""
    key: str
    name: str
    path: str
    is_pdf: bool
    head: str | None
    built_at: str | None


@dataclass(frozen=True)
class PinFacts:
    """What the renderer knows about one open or awaiting-review pin beyond its record - facts other parts decide.

    doc_key: the document the pin belongs to (a legacy record without one belongs to the first document).
    location: a line pin's file as the location column shows it - relative to --manuscript when it can be placed
    there, else the stored file's name (or the record's name); empty for a view-only PDF's pin, which has no file.
    line_len: the length of the pin's one line when the pin is open, spans exactly one line, carries a quote and its
    file is placed under --manuscript; None otherwise - the long-line quote exception reads nothing else of the file.
    badge: the overlap badge ('#N 범위 안', ...) or "". reopened: reopened since its last close. addressed: logins it
    is handed to (the assignee, or a legacy question's @-tags). fyi: logins tagged for reference only. round: the
    thread posts of the current round, oldest first."""
    doc_key: str
    location: str
    line_len: int | None
    badge: str
    reopened: bool
    addressed: tuple[str, ...]
    fyi: tuple[str, ...]
    round: tuple[Record, ...]


@dataclass(frozen=True)
class PinsMdInput:
    """Everything one rendering of pins.md reads.

    rows: every live pin record (open, awaiting review, done), as stored. facts: PinFacts by pin id for each row that
    is open or awaiting review. base: the base URL the guidance's curl examples use; None means loopback (the file
    written to disk), a different value is a remote reader (GET /pins.md through another host). port: the loopback
    port. manuscript, label, repo: the run's --manuscript, paper label and repository URL (None or "" = none).
    docs: the configured documents in order, never empty. people: @-tag candidates by login ({name, ...}).
    now: the epoch seconds claims are measured against. updated: the refresh time as the header shows it.
    token_file: the shell path of this machine's agent token file when it exists, else None."""
    rows: Sequence[Record]
    facts: Mapping[int, PinFacts]
    base: str | None
    port: int
    manuscript: str
    label: str
    repo: str | None
    docs: Sequence[DocHeading]
    people: Mapping[str, Record]
    now: float
    updated: str
    token_file: str | None


def ceil5(minutes: float) -> int:
    """Rounds minutes up to 5-minute steps (minimum 5). Same rule as the viewer's ceil5() - an estimate is approximate, so showing it to the minute would be false precision."""
    return max(5, int(math.ceil(minutes / 5.0 - 1e-9)) * 5)


def claim_md(r: Record, now: float) -> str:
    """The in-progress marker for pins.md's number column - "처리 중(이름, 약 15분)". The remaining estimate is rounded up to 5-minute
    steps, or "예상 초과" if exceeded; a legacy claim made without an estimate shows just the name. The lock auto-expiry time is never
    used (it was misread as the estimated completion time). now is epoch seconds."""
    name = md_cell((r.get("claimed_by") or {}).get("name") or "?")
    eta = r.get("eta_ts")
    if not _is_num(eta):
        return "처리 중(%s)" % name
    left = (float(eta) - now) / 60.0
    return "처리 중(%s, %s)" % (name, "약 %d분" % ceil5(left) if left > 0 else "예상 초과")


def md_cell(v: object, newline: str = " ") -> str:
    """One pins.md table cell. '|' would add a column and a newline would break the row - if a record value
    went in as-is, the table would break (observed: kind 'env:x|y' produced an 8-column row). Every cell goes through this function."""
    s = str("" if v is None else v).replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("|", "\\|").replace("\n", newline)


def region_text_of(r: Record) -> str:
    """A view-only pin's location text: "쪽 3, 영역 가로 12-55% 세로 30-48%"."""
    frac = r.get("frac")
    fr = frac if isinstance(frac, list) and len(frac) == 4 else [0, 0, 0, 0]
    try:
        x, y, w, h = [float(v) * 100 for v in fr]
    except (TypeError, ValueError):
        x = y = w = h = 0.0
    return "쪽 %s, 영역 가로 %d–%d%% 세로 %d–%d%%" % (r.get("page", "?"), round(x), round(x + w), round(y), round(y + h))


def location_col(r: Record, facts: PinFacts) -> str:
    """The location column: the file (facts.location - relative to --manuscript, so for a root file the basename, as
    before) and the line range. A view-only PDF's pin has no line, so it's "쪽 N, 영역 ..." instead (the PDF path is in
    the document section header)."""
    if is_region_pin(r):
        return md_cell(region_text_of(r))
    return "`%s L%s-L%s`" % (md_cell(facts.location), md_cell(r.get("lo")), md_cell(r.get("hi")))


def range_label(r: Record) -> str:
    """Range column: if scope is set, env* -> env:<name>, para -> paragraph, raw/lines -> lines; otherwise the legacy kind.
    Every branch escapes via md_cell (missing that on just the env branch used to be a bug)."""
    if is_region_pin(r):
        return "영역"
    scope = r.get("scope")
    if scope and str(scope).startswith("env"):
        k = str(r.get("kind") or "")
        return md_cell(k if k.startswith("env:") else "env:%s" % (k or "?"))
    if scope == "para":
        return "paragraph"
    if scope in ("raw", "lines"):
        return "lines"
    return md_cell(r.get("kind") or "")


def render_quote(r: Record, facts: PinFacts) -> str:
    """The «quote...» exception: only when the pin range is a single line, that line exceeds 600 characters, and scope is raw/para/absent.
    Always attached for a view-only PDF's pin - with no line number, the region text is the agent's only clue to the source.
    The line's length is facts.line_len (None when the file is outside the tree - never read - or has no such line)."""
    if is_region_pin(r):
        q = r.get("quote")
        return "«%s» " % md_cell(q) if q else ""
    scope = r.get("scope")
    if scope not in (None, "raw", "para"):
        return ""
    lo, hi = r.get("lo"), r.get("hi")
    if not (_is_int(lo) and _is_int(hi)) or lo != hi:
        return ""
    q = r.get("quote")
    if not q:
        return ""
    if facts.line_len is None or facts.line_len <= 600:
        return ""
    # q was already truncated by truncate_quote() when it was saved (an ellipsis is already attached if it
    # was cut) - truncating again to 60 characters here would cut into that ellipsis and look
    # double-truncated. Only the pipe character is escaped.
    return "«%s» " % md_cell(q)


def josa(n: object, cons: str, vowel: str) -> str:
    """Korean particle after a number - '#20과'/'#2와', '#20을'/'#2를'. Decided by the final sound of the Sino-Korean reading:
    ending in 0 (ship/baek/cheon/man/yeong) takes the consonant-final particle, and so do the digits 1/3/6/7/8
    (il/sam/yuk/chil/pal). Same rule as the viewer's josa()."""
    d = str(n)[-1:]
    return cons if d == "0" or d in "13678" else vowel


def rel_badge(rel: Sequence[Mapping[str, Any]], by_id: Mapping[int, Record], me: Record | None = None) -> str:
    """Picks one representative relationship for pins.md / card tags - phrased as a short, meaningful label (the old ⊂#N/∩#N marks were unreadable).

    1. If there's a pin with the exact same range (the same spot marked twice), the one with the smallest id: '#N과 같은 범위'
    2. If there's an inside relationship, the smallest enclosing outer pin: '#N 범위 안'
    3. The smallest-id partial: '#N과 일부 겹침'
    contains (wraps) is never shown. Since the rel entries from GET /api/pins are only {id,rel} (the
    contract), ranges are looked up from by_id (the full rows). Without me (this pin), same-range pins
    can't be singled out, so it falls back to only inside/overlap, as before. The viewer's relBadge() is the same rule."""
    if me is not None:
        same = [x for x in rel if (by_id.get(x["id"]) or {}).get("lo") == me.get("lo")
                and (by_id.get(x["id"]) or {}).get("hi") == me.get("hi")]
        if same:
            n = min(x["id"] for x in same)
            return "#%d%s 같은 범위" % (n, josa(n, "과", "와"))
    insides = [x for x in rel if x["rel"] == "inside"]
    if insides:
        def span(x: Mapping[str, Any]) -> tuple[int, int]:
            """The enclosing pin's line span (unknown pins last), then its id - the smallest enclosing pin wins."""
            o = by_id.get(x["id"])
            return ((o["hi"] - o["lo"]) if o else 1 << 30, x["id"])
        best = min(insides, key=span)
        return "#%d 범위 안" % best["id"]
    partials = [x for x in rel if x["rel"] == "partial"]
    if partials:
        n = min(partials, key=lambda x: x["id"])["id"]
        return "#%d%s 일부 겹침" % (n, josa(n, "과", "와"))
    return ""


LEGEND = ("표시: '#N 범위 안'·'#N과 같은 범위' = N과 한 번에 고치고 둘 다 닫는다 · '#N과 일부 겹침' = 참고만, 각자 처리해도 된다 · "
          "'처리 중(이름, 약 N분)' = 다른 에이전트가 잡음, 건너뛴다 · '수정됨' = 저장 뒤 메모·범위가 바뀜 · "
          "'위치 잃음' = 위치를 되찾지 못함(네가 방금 고친 곳이면 확인 후 닫아도 된다) · "
          "'질문' = 고칠 곳이 아니라 물음이다, 답글(reply)로 답하고 닫는다 · "
          "'다시 열림' = 검토에서 되돌아온 핀, 메모 칸의 '다시 연 이유'대로 다시 고친다 · "
          "'→ @이름' = 담당이 사람인 핀(담당 없는 옛 핀은 사람에게 물은 질문 핀), 사용자가 따로 시키지 않으면 건너뛴다 · "
          "'참고 @이름' = 알림만 간 참고용 태그다, 담당이 아니므로 건너뛰지 않는다 · "
          "«…» = 줄 안에서 가리킨 부분의 렌더 글자(검색 힌트, 원문과 다를 수 있음)")
# v0.2: the one header line added to pins.md - how an agent authenticates (docs/handbook/api.md §인증).
TOKEN_GUIDANCE = ("에이전트 인증: 모든 요청에 `Authorization: Bearer <토큰>` 헤더를 붙인다(`curl -H \"Authorization: Bearer $LIMN_TOKEN\" …`, "
                  "토큰은 사용자가 `limn token create <인스턴스>` 로 발급해 준다) · "
                  "헤더 없는 로컬 요청을 에이전트로 받는 방식은 폐지 예정이다 · "
                  "테일넷 주소(원격)로 오는 신원 헤더 없는 요청(태그 장치 등)은 403 이다 — 원격 에이전트는 반드시 토큰을 붙인다")


def token_guidance_line(shown_file: str | None) -> str:
    """The agent-auth line of pins.md: TOKEN_GUIDANCE as before, plus one clause when this machine's agents have a token
    file to send (shown_file, its shell path; None = no file yet, or a remote reader who cannot reach it). The clause
    is appended after the old text, never woven in, so the line still starts with what agents already match."""
    if not shown_file:
        return TOKEN_GUIDANCE
    return (TOKEN_GUIDANCE + " · 이 기기의 에이전트는 토큰 파일을 붙인다: " + token_file_curl(shown_file)
            + "(파일 내용은 출력하지도 저장소에 옮기지도 않는다)")


REPLY_GUIDANCE = ("답글(0.2.2): 사람 신원으로 단 답글은 검토 대기·완료 핀을 다시 연다(답글이 다시 연 이유가 된다) — "
                  "토큰 없이 사람 신원을 달고 가는 에이전트(테일넷 주소로 닫을 때 `\"review\":true` 를 넣는 경우, `--auth local` 의 "
                  "헤더 없는 curl)는 답글 본문에 `\"reopen\":false` 를 넣는다 · 토큰을 쓰는 에이전트의 답글은 상태를 바꾸지 않는다")


def claim_guidance(base: str) -> str:
    """v0.2.1: the line after the close instruction - how to claim a pin (the legend only explained the marker)."""
    return ("처리를 시작하는 핀은 먼저 잡는다 — `curl -X POST -H 'Content-Type: application/json' -d '{\"eta_min\":15}' "
            "%s/api/pins/N/claim`(eta_min = 예상 분, 번호 칸에 '처리 중(이름, 약 N분)' 으로 보인다) · 고치기 직전에 그 핀 하나만 "
            "잡는다 · 409 면 다른 쪽이 잡은 핀이니 건너뛴다 · 포기하면 `%s/api/pins/N/unclaim`" % (base, base))


THREAD_MD_SHOW = 3                 # number of current-round thread posts shown in pins.md's note column (from the end)
THREAD_MD_CHARS = 200              # character count for one of those posts - the full text is via GET /api/pins/N


def flat(s: object, n: int) -> str:
    """Collapses whitespace/newlines to a single space and truncates at n characters (with an ellipsis if cut).
    None and "" both give "". The one rule for a text shown on one line: pins.md's thread posts and close replies
    here, and the excerpt of an events.jsonl notice (limn.events.make_event)."""
    return truncate_quote(" ".join(str(s or "").split()), n)


def thread_md(r: Record, facts: PinFacts) -> str:
    """The current round's thread (facts.round), appended after pins.md's note column: "[스레드 2건] 서준: ... ⏎ 다시 연 이유(서준): ...".
    Included so an agent never misses a follow-up question or reopen reason. If long, only the last THREAD_MD_SHOW entries are shown; the rest via GET /api/pins/N."""
    msgs = [m for m in facts.round if m.get("ev") != "close" and (m.get("text") or not m.get("ev"))]
    if not msgs:
        return ""
    shown = msgs[-THREAD_MD_SHOW:]
    parts = []
    for m in shown:
        name = (m.get("by") or {}).get("name") or (m.get("by") or {}).get("login") or "?"
        label = "다시 연 이유(%s)" % name if m.get("ev") == "reopen" else "담당 바꿈(%s)" % name if m.get("ev") == "assign" else name
        parts.append("%s: %s" % (label, flat(m.get("text"), THREAD_MD_CHARS)))
    more = len(msgs) - len(shown)
    head = "[스레드 %d건%s]" % (len(msgs), ", 앞 %d건은 GET /api/pins/%s" % (more, r.get("id")) if more else "")
    return head + " " + " ⏎ ".join(parts)


def review_md(rows: Sequence[Record], facts: Mapping[int, PinFacts], sectioned: bool) -> list[str]:
    """The "awaiting review" subsection at the bottom of pins.md - pins closed by an agent that a person hasn't confirmed yet. A
    different 4-column table from the open table, so it's never misread as open pins. The expected confirmer is the author (anyone
    can confirm, but the viewer suggests the author). No subsection at all if empty."""
    if not rows:
        return []
    out = ["", "## 검토 대기 %d건 — 사람이 확인할 차례. 에이전트는 다시 처리하지 않는다(다시 열리면 위 열린 표로 돌아온다)" % len(rows),
           "", "| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |", "|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["id"]):
        f = facts[r["id"]]
        syms = ["%s" % r.get("id")] + (["질문"] if r.get("kind_req") == "question" else [])
        loc = location_col(r, f)
        if sectioned:
            loc = "`%s` · %s" % (md_cell(f.doc_key), loc)
        who_ = (r.get("author") or {}).get("name") or (r.get("author") or {}).get("login") or "작성자 기록 없음"
        ans = flat(r.get("close_reply"), THREAD_MD_CHARS) or "(설명 없이 닫힘)"
        if r.get("close_ref"):
            ans += " (%s)" % flat(r["close_ref"], 80)
        out.append("| %s | %s | %s | %s |" % (md_cell(" · ".join(syms)), loc, md_cell(who_), md_cell(ans)))
    return out


def pins_md_text(page: PinsMdInput) -> str:
    """The summary an agent reads in one pass. Snippets are deliberately omitted -
    given just a line range, an agent reading the source directly is always cheaper and more accurate.
    Only %s is used as a format specifier - so a single malformed record never kills the whole summary.
    Closed pins are never listed (only counted in the header line) - so pins.md's size doesn't grow as they pile up.

    page.base (docs/handbook/api.md §원격 에이전트 진입점): the base URL the guidance line's close example uses. If None (the default path written
    to disk), it's loopback, as now. GET /pins.md passes the value rewritten to the request Host - only when
    it's a remote base does a "원격: curl ..." line get appended to the guidance paragraph (omitted for
    loopback, since that means the file is already being read locally), and the token-file clause is left out
    (a remote reader cannot reach this machine's file).

    Multiple documents (§Multiple documents): kept as a single sheet, grouped into per-document subsections
    (## name - key - path). With a single document and no open pins under any other document key, it keeps the old shape with no subsections."""
    rows, facts = page.rows, page.facts
    loopback_base = "http://127.0.0.1:%d" % page.port
    is_remote = page.base is not None and page.base != loopback_base
    base = page.base or loopback_base
    openn = [r for r in rows if not r.get("done")]
    reviewn = [r for r in rows if isinstance(parse_pin(r), ReviewPin)]
    n_done = len(rows) - len(openn) - len(reviewn)

    # The author's name is prefixed to the note only when there are 2+ authors (by login; legacy pins with no author
    # count as one group) - docs/handbook/api.md §메모 칸의 덧붙임.
    author_groups = set()
    for r in openn:
        a = r.get("author")
        author_groups.add(a.get("login") if a and a.get("login") else None)
    multi_author = len(author_groups) > 1

    rows_by_doc: dict[str, list[str]] = {}
    any_symbol = False
    people = page.people
    n_human = 0
    for r in openn:
        f = facts[r["id"]]
        syms = []
        # Number-column priority (reopened > -> @ > question): the most urgent signal to re-check goes leftmost.
        if f.reopened:
            syms.append("다시 열림")
        to = f.addressed
        if to:                                    # a pin handed to a person (assignee = a person, or a legacy pin's question @-tag) - an agent skips it
            n_human += 1
            syms.append("→ " + ", ".join("@%s" % ((people.get(lg) or {}).get("name") or lg) for lg in to))
        fyi = f.fyi
        if fyi:                                    # FYI @-tags - notification only, never skipped
            syms.append("참고 " + ", ".join("@%s" % ((people.get(lg) or {}).get("name") or lg) for lg in fyi))
        if r.get("kind_req") == "question":
            syms.append("질문")
        if f.badge:
            syms.append(f.badge)
        if claim_holds(r, page.now):
            syms.append(claim_md(r, page.now))
        if r.get("edited_at"):
            syms.append("수정됨")
        if r.get("stale"):
            syms.append("위치 잃음")
        if syms:
            any_symbol = True
        idcol = md_cell(" · ".join(["%s" % r.get("id")] + syms))
        note = md_cell(r.get("note") or "", newline=" ⏎ ")
        th = thread_md(r, f)
        if th:
            note = (note + " ⏎ " if note else "") + md_cell(th)
        if multi_author:
            an = (r.get("author") or {}).get("name")
            if an:                                 # '[name]' rather than '@name' - so it's never misread as an @-tag (observed)
                note = "[%s] " % md_cell(an) + note
        q = render_quote(r, f)
        if q:
            any_symbol = True
            note = q + note
        rows_by_doc.setdefault(f.doc_key, []).append(
            "| %s | %s | %s | %s | %s |" % (idcol, md_cell(r.get("page", 0)), location_col(r, f), range_label(r), note))

    docs = page.docs
    known = [d.key for d in docs]
    sectioned = len(docs) > 1 or any(k not in known[:1] for k in rows_by_doc)
    n_region = sum(1 for r in openn if is_region_pin(r))

    out = ["# 수정 요청 핀", "", "원고: `%s`" % page.manuscript,
           "논문: %s · 저장소: %s" % (page.label, page.repo or "(없음)")]
    if not sectioned:
        head_short, built_at = docs[0].head, docs[0].built_at   # the one document
        if head_short and head_short != "-" and built_at:           # omitted if either is absent (docs/handbook/api.md §머리줄)
            out.append("기준: %s · 빌드 %s" % (head_short, built_at))
            out.append("다른 체크아웃에서 처리하면 먼저 `git rev-parse --short HEAD` 가 같은지 확인")
    else:
        parts = []
        for d in docs:
            parts.append("%s(`%s`%s) %d건" % (md_cell(d.name), d.key, ", 보기 전용" if d.is_pdf else "",
                                              len(rows_by_doc.get(d.key, []))))
        for k in rows_by_doc:
            if k not in known:
                parts.append("설정에 없는 문서(`%s`) %d건" % (md_cell(k), len(rows_by_doc[k])))
        out.append("문서: " + " · ".join(parts))
        out.append("핀은 아래 문서별 소절(`## 이름 · 키 · 경로`)로 묶였다 — 위치 칸의 경로는 `--manuscript` 기준. "
                   "소절의 `기준:` 커밋이 다른 체크아웃에서 처리하면 먼저 `git rev-parse --short HEAD` 가 같은지 확인")
    out.append("갱신: %s  ·  열린 핀 %d건  ·  %s닫힌 핀 %d건(뷰어의 '닫힌 핀'에서 확인)" %
               (page.updated, len(openn),
                "검토 대기 %d건(맨 아래, 처리하지 않는다)  ·  " % len(reviewn) if reviewn else "", n_done))
    out.append("")
    guidance = ("처리한 핀은 닫는다 — 닫을 때 `changes` 에 이 핀 때문에 바꾼 줄 범위를, `ref` 에 `PR #번호 (커밋 해시)` 를 적는다: "
                "`curl -X POST -H 'Content-Type: application/json' "
                "-d '{\"reply\":\"무엇을 고쳤는지(≤500자)\",\"ref\":\"PR #12 (커밋 해시)\","
                "\"changes\":[{\"file\":\"main.tex\",\"lo\":12,\"hi\":14}]}' "
                "%s/api/pins/N/close`(본문 생략 가능, 그러면 옛 방식처럼 사유 없이 닫힘. `changes` 의 줄 번호는 `ref` 의 "
                "커밋이 만든 판 기준 — 스쿼시 머지 뒤 닫으면 머지된 main 기준, 경로는 위치 칸 기준. "
                "핀마다 커밋을 나누면 더 좋지만 필수는 아니다) · "
                "줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다 · "
                "'질문' 핀은 원고를 고치지 말고(질문이 수정을 뜻할 때만 고친다) `curl -X POST -H 'Content-Type: application/json' "
                "-d '{\"text\":\"답(≤1000자)\"}' %s/api/pins/N/reply` 로 답한 뒤 닫는다 · "
                "에이전트가 닫은 핀은 완료가 아니라 검토 대기로 간다(사람이 뷰어에서 [확인]) — 테일넷 주소로 닫는 에이전트는 "
                "요청이 사람 신원을 달고 가므로 본문에 `\"review\":true` 를 넣는다 · 검토 대기 핀은 다시 처리하지 않는다 · "
                "에이전트는 확인(confirm)하지 않는다 — `/api/pins/N/confirm` 은 사람 신원(테일넷 헤더)이 없으면 403" % (base, base))
    if n_human:
        guidance += (" · 번호 칸에 `→ @이름` 이 붙은 핀 %d건은 담당이 사람인 핀이다 — 요청한 사용자가 그 핀을 "
                     "명시적으로 시키지 않으면 건너뛴다(`참고 @이름`은 알림만 간 참고용 태그라 건너뛰지 않는다)" % n_human)
    if is_remote:
        guidance += " · 원격: `curl -s %s/pins.md`" % base
    if page.repo:
        guidance += (" · 처리 전 자기 체크아웃의 `git remote get-url origin` 이 위 저장소와 같은지 확인. "
                      "다르면 다른 논문의 핀이니 멈춘다")
    if n_region:
        guidance += (" · 보기 전용 PDF 의 핀은 줄 번호가 없다 — 쪽·영역 글자(«…»)·메모로 무엇을 가리키는지 판단하고, "
                     "고칠 곳은 LaTeX 문서에서 찾는다(못 찾으면 닫지 말고 보고)")
    out.append(guidance)
    out.append(claim_guidance(base))
    out.append(token_guidance_line(None if is_remote else page.token_file))
    out.append(REPLY_GUIDANCE)                    # v0.2.2: one more additive line
    if any_symbol:
        out.append(LEGEND)
    header = ["| # | 쪽 | 위치 | 범위 | 메모 |", "|---|---|---|---|---|"]
    if not sectioned:
        rows_render = rows_by_doc.get(known[0], [])
        out += [""] + header
        out += rows_render if rows_render else ["| — | — | 열린 핀 없음 | | |"]
        return "\n".join(out + review_md(reviewn, facts, sectioned)) + "\n"
    shown = 0
    for d in docs:
        rs = rows_by_doc.get(d.key)
        if not rs:
            continue
        shown += 1
        title = "## %s · `%s` · `%s`" % (md_cell(d.name), d.key, md_cell(d.path))
        if d.is_pdf:
            title += " — 보기 전용 PDF(줄 번호 없음)"
        out += ["", title]
        if d.head and d.head != "-" and d.built_at:
            out.append("기준: %s · %s %s" % (d.head, "그림" if d.is_pdf else "빌드", d.built_at))
        out += [""] + header + rs
    for k, rs in rows_by_doc.items():
        if k in known:
            continue
        shown += 1
        out += ["", "## 설정에 없는 문서 · `%s` — 이 뷰어의 --doc 목록에 없다. 처리 전에 사용자에게 확인" % md_cell(k),
                ""] + header + rs
    if not shown:
        out += ["", "열린 핀 없음"]
    return "\n".join(out + review_md(reviewn, facts, sectioned)) + "\n"


def _is_num(v: object) -> TypeGuard[int | float]:
    """An int or float that is not a bool - how a stored eta_ts (epoch seconds) is recognised."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: object) -> bool:
    """An int that is not a bool - how a stored line number is recognised."""
    return isinstance(v, int) and not isinstance(v, bool)

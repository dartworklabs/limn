"""Request parsing: every value a route takes from a JSON body or a query string, checked once at the boundary (R3).

Each parser returns the value the service takes, or an InputRejected carrying the exact 400 message and reason of the
agent contract (docs/handbook/api.md §오류 응답); the handler answers a refusal with web.answers.accepted(). Parsers
never raise for bad input. When a request is refused for several fields, the first one in the order the server has
always checked them is the one answered, so each parser keeps that order.

Most parsers look at the request alone. The location parsers of a new pin, an edit's re-placement, a selection and
a snippet also check the request against the manuscript - that a named file lies in the tree, that lines lie in the
file, that a page is in the build. They read those facts through DocumentFacts, which the composition root
(server.document_facts) supplies for the request's document; nothing here reads a file itself, apart from resolving
a named path against the tree (limn.files.file_in_tree and the close's `changes`).
"""
from __future__ import annotations

import math
import os
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, Protocol, TypeAlias

from limn.build import valid_build_name
from limn.files import BadPath, NotAFile, OutsideTree, file_in_tree
from limn.mapping import norm, truncate_quote
from limn.pins.edit import (
    ASSIGNEE_AGENT, KIND_REQS, LOCAL_LOGIN, NOTE_MAX, PDF_QUOTE_MAX, AddRequest, EditRequest, LinePlace, Place,
    RegionPlace,
)
from limn.web.errors import InputRejected

Json: TypeAlias = Mapping[str, Any]        # a request's JSON object
Query: TypeAlias = Mapping[str, list[str]]  # parse_qs() of a query string

CLOSE_REPLY_MAX = 500              # what-was-fixed note left when closing (§P0b-보완 C)
CLOSE_REF_MAX = 80                 # reference (e.g. PR number) - matching values let the UI group closed pins together
CLOSE_CHANGES_MAX = 50             # v0.3: ranges in one close body's optional changes (the new-side lines the agent changed for the pin)
CHANGE_LINE_MAX = 1_000_000       # a line number past this is not a manuscript line
CLAIM_TTL_DEFAULT = 120            # minutes - lock duration used when neither ttl_min nor eta_min is given for a claim (§P0c-C)
CLAIM_TTL_MIN = 1
CLAIM_TTL_MAX = 120                # the lock auto-expiring is a safety net - at 480 a stuck agent held a pin for half a day (observed 23 times)
CLAIM_ETA_MIN = 1                  # minutes - estimated time to handle (eta_min). Shown in the UI rounded up to 5-minute steps
CLAIM_ETA_MAX = 240
CLAIM_TTL_FLOOR = 30               # if only eta_min is given, the lock is min(ceiling, max(this floor, eta x 2)) - even a short estimate holds for 30 min
THREAD_TEXT_MAX = 1000             # one reply - like the note (NOTE_MAX), only string/length are checked; the UI renders it via esc()
MENTION_MAX = 10                   # cap on mention hints per post
SCOPES = ("raw", "para", "env", "env2", "env3", "lines")
ADD_FIELDS = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score",
              "frac", "note", "scope", "quote", "pdf_build")
REGION_FIELDS = ("page", "frac", "note", "quote", "pdf_build")
REGION_EDIT_REFUSAL = "보기 전용 문서의 핀에는 줄 범위가 없습니다 — 메모(note)와 영역(loc: page, frac)만 고칩니다."
PDF_BUILD_REFUSAL = "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다."
REVISION_BUILD_FIELDS = frozenset({"commit", "doc", "pin"})


class DocumentFacts(Protocol):
    """What the location parsers read about one document and its manuscript, supplied per request by the composition
    root (server.document_facts). Every method reads the disk at call time."""

    @property
    def key(self) -> str:
        """The document key (?doc=); a view-only document's refusals name it."""
        ...

    @property
    def is_pdf(self) -> bool:
        """True for a view-only PDF document: its pins are regions, it has no source lines."""
        ...

    @property
    def pdf(self) -> Path:
        """A view-only document's PDF (its main file), which a region pin records."""
        ...

    @property
    def root(self) -> Path:
        """The manuscript tree (--manuscript) a pin's or snippet's file must lie in."""
        ...

    def lines(self, path: Path) -> list[str]:
        """The lines of a manuscript file; [] when it cannot be read as UTF-8."""
        ...

    def page_count(self, build: str | None) -> int:
        """How many pages build `build` (a valid page directory name) has, or the build on screen for None or a build
        that is gone."""
        ...

    def current_build(self) -> str:
        """The name of the page directory on screen."""
        ...

    def pick_pages(self, build: str | None) -> tuple[Path, list[tuple[float, float]]] | None:
        """The page directory a selection is traced in and each page's (width, height) in points: build's own (a valid
        name), or the one on screen for None. None when build names a page directory that is gone."""
        ...


def _is_int(v: object) -> bool:
    """An int that is not a bool - how a JSON integer arrives from json.loads."""
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str_list(v: object) -> bool:
    """A JSON list of strings."""
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _first(q: Query, key: str, default: str | None = None) -> str | None:
    """The first value of query parameter `key`, or default when the query has none."""
    values = q.get(key)
    return values[0] if values else default


def int_field(v: object, what: str) -> int | InputRejected:
    """An integral JSON number (1 and 1.0 both give 1; a bool, NaN or 1.5 does not) named `what` in the refusal."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or int(v) != v:
        return InputRejected("%s 는 정수여야 합니다." % what, "not_integer")
    return int(v)


def num_field(v: object, what: str) -> float | InputRejected:
    """A finite JSON number other than a bool, as a float, named `what` in the refusal."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return InputRejected("%s 는 유한한 숫자여야 합니다." % what, "not_number")
    return float(v)


def parse_note(v: object) -> str | InputRejected:
    """A pin's note: a string of at most NOTE_MAX characters; absent or null is the empty note."""
    if v is None:
        return ""
    if not isinstance(v, str):
        return InputRejected("note 는 문자열이어야 합니다.", "bad_note")
    if len(v) > NOTE_MAX:
        return InputRejected("메모가 너무 깁니다(%d자 이하)." % NOTE_MAX, "note_too_long")
    return v


def parse_kind_req(v: object) -> str | None | InputRejected:
    """Pin kind - 'fix' (fix request) | 'question'. None if absent (= fix, same as a legacy pin)."""
    if v is None:
        return None
    if not isinstance(v, str) or v not in KIND_REQS:
        return InputRejected("kind_req 는 %s 중 하나입니다." % "|".join(KIND_REQS), "bad_kind_req")
    return v


def parse_mention_hints(v: object) -> list[str] | InputRejected:
    """The viewer's @-tag hints: at most MENTION_MAX login strings, used to pick among people who share a name."""
    if v is None:
        return []
    if not isinstance(v, list) or not _is_str_list(v) or len(v) > MENTION_MAX:
        return InputRejected("mentions 는 로그인 문자열 목록(%d개 이하)입니다." % MENTION_MAX, "bad_mentions")
    return v


def parse_assignee(v: object, known: Collection[str]) -> str | None | InputRejected:
    """Assignee - "agent" or the login of a person this viewer knows. None if absent (not sent = unchanged).

    known is the logins of known_people(), which the caller reads only when the body names an assignee
    (server.assignee_people)."""
    if v is None:
        return None
    if v == ASSIGNEE_AGENT:
        return ASSIGNEE_AGENT
    if not isinstance(v, str) or not v or v == LOCAL_LOGIN:
        return InputRejected("assignee 는 'agent' 또는 사람의 로그인(문자열)입니다.", "bad_assignee")
    if v not in known:
        return InputRejected("담당(assignee) '%s' 은(는) 이 뷰어가 아는 사람이 아닙니다 — 'agent' 또는 뷰어를 연 적 있는 테일넷 사람의 로그인을 쓰세요." % v, "unknown_assignee")
    return v


def parse_thread_text(v: object, what: str = "text", required: bool = True) -> str | None | InputRejected:
    """One reply or reopen reason. Like a note, only string type and length are checked (the screen renders via esc()).
    Newlines are normalized to \\n and control characters (other than newline/tab) are stripped - so the pins.md table
    and notification bodies don't break. Empty after trimming whitespace is refused when required, else None; so is
    an absent value. `what` names the field in the refusal."""
    if v is None:
        if required:
            return InputRejected("%s 가 필요합니다." % what, "text_required")
        return None
    if not isinstance(v, str):
        return InputRejected("%s 는 문자열이어야 합니다." % what, "bad_text")
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    v = "".join(ch for ch in v if ch in "\n\t" or not (ord(ch) < 32 or 127 <= ord(ch) < 160)).strip()
    if len(v) > THREAD_TEXT_MAX:
        return InputRejected("%s 가 너무 깁니다(%d자 이하)." % (what, THREAD_TEXT_MAX), "text_too_long")
    if not v:
        if required:
            return InputRejected("%s 가 비어 있습니다." % what, "text_empty")
        return None
    return v


def parse_reply_text(v: object) -> str | InputRejected:
    """A reply's required text (parse_thread_text with required=True, which never gives None)."""
    text = parse_thread_text(v)
    return "" if text is None else text


def parse_reopen_flag(d: Json) -> bool | None | InputRejected:
    """The reply body's optional reopen - true/false overrides the rule, absent (None) lets the server decide."""
    v = d.get("reopen")
    if v is not None and not isinstance(v, bool):
        return InputRejected("reopen 은 true/false 입니다(없으면 서버 규칙을 따릅니다).", "bad_reopen")
    return v


def parse_review_flag(d: Json) -> bool | None | InputRejected:
    """The close body's optional review - true means awaiting review, false means done right away. None if absent
    (left to the closer to decide)."""
    v = d.get("review")
    if v is not None and not isinstance(v, bool):
        return InputRejected("review 는 true/false 입니다.", "bad_review")
    return v


class CloseBody(NamedTuple):
    """A close's optional reply and ref, each None when absent or blank."""
    reply: str | None
    ref: str | None


def parse_close_body(d: Json) -> CloseBody | InputRejected:
    """The close body's optional {"reply", "ref"} fields. Absent or an empty (whitespace-only) string both become
    None - preserving the existing "curl POST with no body" behavior (§P0b-보완 C)."""
    reply = d.get("reply")
    if reply is not None:
        if not isinstance(reply, str):
            return InputRejected("reply 는 문자열이어야 합니다.", "bad_reply")
        if len(reply) > CLOSE_REPLY_MAX:
            return InputRejected("reply 가 너무 깁니다(%d자 이하)." % CLOSE_REPLY_MAX, "reply_too_long")
        if not reply.strip():
            reply = None
    ref = d.get("ref")
    if ref is not None:
        if not isinstance(ref, str):
            return InputRejected("ref 는 문자열이어야 합니다.", "bad_ref")
        if len(ref) > CLOSE_REF_MAX:
            return InputRejected("ref 가 너무 깁니다(%d자 이하)." % CLOSE_REF_MAX, "ref_too_long")
        if not ref.strip():
            ref = None
    return CloseBody(reply, ref)


class CloseChange(NamedTuple):
    """One validated range of a close body's `changes` (parse_close_changes), immutable: an absolute, resolved path
    inside the manuscript folder, and the new-side lines 1 ≤ lo ≤ hi ≤ CHANGE_LINE_MAX the agent changed for the pin."""
    file: str
    lo: int
    hi: int

    def record(self) -> dict[str, Any]:
        """The JSON shape stored on the pin record (api.md §핀 레코드 스키마): {file, lo, hi}."""
        return {"file": self.file, "lo": self.lo, "hi": self.hi}


def parse_close_changes(v: object, root: Path) -> tuple[CloseChange, ...] | None | InputRejected:
    """The close body's optional `changes`: [{file, lo, hi}] - the new-side lines the agent changed for this pin. file is
    a path inside root (the manuscript folder), absolute or relative to it (the pins.md location column); the result
    carries it resolved and absolute, like a pin's file. Absent or [] -> None (the pre-0.3 close). A refusal names the
    offending item - the messages are part of the agent contract."""
    if v is None:
        return None
    if not isinstance(v, list):
        return InputRejected("changes 는 [{\"file\", \"lo\", \"hi\"}] 목록이어야 합니다.", "bad_changes")
    if len(v) > CLOSE_CHANGES_MAX:
        return InputRejected("changes 는 %d개 이하여야 합니다." % CLOSE_CHANGES_MAX, "too_many_changes")
    out, base = [], root.resolve()
    for i, c in enumerate(v):
        what = "changes[%d]" % i
        if not isinstance(c, dict) or set(c) != {"file", "lo", "hi"}:
            return InputRejected("%s 는 file·lo·hi 세 필드만 가진 객체여야 합니다." % what, "bad_changes")
        f, lo, hi = c["file"], c["lo"], c["hi"]
        if not isinstance(f, str) or not f.strip() or len(f) > 1024 or "\x00" in f:
            return InputRejected("%s.file 은 비어 있지 않은 경로 문자열이어야 합니다." % what, "bad_changes")
        if not (_is_int(lo) and _is_int(hi) and 1 <= lo <= hi <= CHANGE_LINE_MAX):
            return InputRejected("%s 의 lo·hi 는 1 ≤ lo ≤ hi ≤ %d 인 정수여야 합니다." % (what, CHANGE_LINE_MAX), "bad_changes")
        try:
            path = (Path(f) if os.path.isabs(f) else base / f).resolve()
            path.relative_to(base)
        except (ValueError, OSError, RuntimeError):
            return InputRejected("%s.file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다." % what, "change_outside_manuscript")
        out.append(CloseChange(str(path), lo, hi))
    return tuple(out) or None


class ClaimBody(NamedTuple):
    """A claim's minutes until the marker lapses (clamped) and its optional estimate (clamped)."""
    ttl: int
    eta: int | None


def _claim_int(d: Json, key: str, lo: int, hi: int) -> int | None | InputRejected:
    """One optional integer from the body. None if absent. Refused if not an integer or below lo; clamped to hi if it
    exceeds the ceiling.

    Clamping is for backward compatibility - so an agent that still sends the old ttl_min=480 doesn't break
    when trying to extend with the same value after the ceiling was lowered to 120, instead of getting a 400.
    The value actually applied is returned as *_applied in the response."""
    if key not in d:
        return None
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or int(v) != v:
        return InputRejected("%s 은 정수여야 합니다." % key, "not_integer")
    n = int(v)
    if n < lo:
        return InputRejected("%s 은 %d 이상이어야 합니다(상한 %d 를 넘으면 %d 로 깎아 받습니다)." % (key, lo, hi, hi), "too_small")
    return min(n, hi)


def parse_claim_body(d: Json) -> ClaimBody | InputRejected:
    """The claim body -> (ttl_min, eta_min or None). Both are optional; eta_min is checked first.

    eta_min (1..240) is the estimated time to handle - shown in the viewer as "in progress - about 15 min -
    around 20:40". ttl_min (1..120) is the time until the lock auto-expires (a safety net). Values past the
    ceiling are clamped to it (compatible with the legacy ttl_min 480). If ttl_min is omitted, it's
    min(120, max(30, eta x 2)) when eta_min is given, otherwise 120."""
    eta = _claim_int(d, "eta_min", CLAIM_ETA_MIN, CLAIM_ETA_MAX)
    if isinstance(eta, InputRejected):
        return eta
    ttl = _claim_int(d, "ttl_min", CLAIM_TTL_MIN, CLAIM_TTL_MAX)
    if isinstance(ttl, InputRejected):
        return ttl
    if ttl is None:
        ttl = min(CLAIM_TTL_MAX, max(CLAIM_TTL_FLOOR, eta * 2)) if eta is not None else CLAIM_TTL_DEFAULT
    return ClaimBody(ttl, eta)


def parse_pin_param(v: object) -> int | None | InputRejected:
    """The optional pin of a revision request (query string or JSON int): None if absent or empty, else a pin id
    1..999999999. Whether the pin exists is decided later."""
    if v is None or v == "":
        return None
    if isinstance(v, str) and re.fullmatch(r"[1-9][0-9]{0,8}", v):
        return int(v)
    if isinstance(v, int) and _is_int(v) and 1 <= v <= 999999999:
        return v
    return InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin")


class RevisionQuery(NamedTuple):
    """A revision route's commit (as sent; the service checks it) and optional pin."""
    commit: str
    pin: int | None


def parse_revision_query(q: Query) -> RevisionQuery | InputRejected:
    """GET /api/revision-diff|-build|-pdf: ?commit= (empty when absent) and the optional &pin= (parse_pin_param)."""
    pin = parse_pin_param(_first(q, "pin"))
    if isinstance(pin, InputRejected):
        return pin
    return RevisionQuery(_first(q, "commit", "") or "", pin)


class RevisionBuild(NamedTuple):
    """POST /api/revision-build's commit (as sent - any JSON value; the service checks it) and optional pin."""
    commit: object
    pin: int | None


def parse_revision_build(d: Json) -> RevisionBuild | InputRejected:
    """POST /api/revision-build's body: only commit, doc and pin; pin, when present, a JSON integer in range."""
    if set(d) - REVISION_BUILD_FIELDS:
        return InputRejected("허용되지 않는 비교 PDF 요청 필드입니다.", "unknown_fields")
    if "pin" in d and not _is_int(d["pin"]):
        return InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin")
    pin = parse_pin_param(d.get("pin"))
    if isinstance(pin, InputRejected):
        return pin
    return RevisionBuild(d.get("commit"), pin)


def parse_event_cursor(v: str | None) -> int | None | InputRejected:
    """GET /api/meta's ?ev= - the last event seq the viewer saw, or None when absent."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return InputRejected("ev 는 정수(마지막으로 본 이벤트 seq)입니다.", "bad_event_cursor")


def parse_doc_key(q: Query | None, body: Json | None = None) -> str | None | InputRejected:
    """The document a request names: ?doc= or the body's doc - the two must agree, and the body's must be a string.
    None (or "") when neither names one; which document that means is the server's (server.request_doc)."""
    key = _first(q, "doc") if q else None
    bkey = body.get("doc") if isinstance(body, Mapping) else None
    if bkey is not None and not isinstance(bkey, str):
        return InputRejected("doc 은 문자열이어야 합니다.", "bad_doc")
    if key and bkey and key != bkey:
        return InputRejected("doc 이 주소(%s)와 본문(%s)에서 다릅니다." % (key, bkey), "doc_mismatch")
    return key or bkey


def source_file(p: object, root: Path) -> Path | InputRejected:
    """The real file inside the manuscript tree root that p names (absolute, or relative to the tree), or why not
    (limn.files.file_in_tree): a bad value, a file outside the tree, or no such file."""
    match file_in_tree(p, root):
        case Path() as f:
            return f
        case BadPath():
            return InputRejected("file 이 올바르지 않습니다.", "bad_file")
        case OutsideTree():
            return InputRejected("원고 디렉토리 밖의 파일입니다: %s" % p, "file_outside_manuscript")
        case NotAFile():
            return InputRejected("원고 안에 그런 파일이 없습니다: %s" % p, "file_not_found")


def parse_loc(d: Json, facts: DocumentFacts) -> dict[str, Any] | InputRejected:
    """A line pin's location fields in the shape to store, or the first field refused.

    file must be a file inside the manuscript tree and 1 <= lo <= hi <= its line count, so this reads that file's
    lines (facts.lines) before checking the range. page defaults to 1; kind, via, score, frac, scope, quote
    (truncated to 60 characters) and pdf_build (a page directory name) are kept when sent.
    """
    out: dict[str, Any] = {}
    f = source_file(d.get("file"), facts.root)
    if isinstance(f, InputRejected):
        return f
    n = len(facts.lines(f))
    lo = int_field(d.get("lo"), "lo")
    if isinstance(lo, InputRejected):
        return lo
    hi = int_field(d.get("hi"), "hi")
    if isinstance(hi, InputRejected):
        return hi
    if not 1 <= lo <= hi <= max(n, 1):
        return InputRejected("줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (n, lo, hi), "range_outside_file")
    out.update(file=str(f), name=f.name, lo=lo, hi=hi)
    page = int_field(d.get("page", 1), "page")
    if isinstance(page, InputRejected):
        return page
    if page < 1:
        return InputRejected("page 는 1 이상이어야 합니다.", "bad_page")
    out["page"] = page
    for k in ("raw_lo", "raw_hi"):
        if d.get(k) is not None:
            raw = int_field(d[k], k)
            if isinstance(raw, InputRejected):
                return raw
            out[k] = raw
    if d.get("kind") is not None:
        if not isinstance(d["kind"], str) or len(d["kind"]) > 80:
            return InputRejected("kind 가 올바르지 않습니다.", "bad_kind")
        out["kind"] = d["kind"]
    if d.get("via") is not None:
        if d["via"] not in ("synctex", "text"):
            return InputRejected("via 는 synctex|text 입니다.", "bad_via")
        out["via"] = d["via"]
    if d.get("score") is not None:
        score = num_field(d["score"], "score")
        if isinstance(score, InputRejected):
            return score
        out["score"] = score
    if d.get("frac") is not None:
        fr = d["frac"]
        if not isinstance(fr, list) or len(fr) != 4:
            return InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac")
        nums = [num_field(x, "frac") for x in fr]
        bad = next((x for x in nums if isinstance(x, InputRejected)), None)
        if bad is not None:
            return bad
        out["frac"] = nums
    if d.get("scope") is not None:
        if d["scope"] not in SCOPES:
            return InputRejected("scope 는 %s 중 하나입니다." % "|".join(SCOPES), "bad_scope")
        out["scope"] = d["scope"]
    if d.get("quote") is not None:
        if not isinstance(d["quote"], str):
            return InputRejected("quote 는 문자열입니다.", "bad_quote")
        out["quote"] = truncate_quote(d["quote"], 60)
    if d.get("pdf_build") is not None:                # the build on screen at drag time (pdf_build from the pick response)
        if not valid_build_name(d["pdf_build"]):
            return InputRejected(PDF_BUILD_REFUSAL, "bad_pdf_build")
        out["pdf_build"] = d["pdf_build"]
    return out


def parse_frac(fr: object) -> list[float] | InputRejected:
    """A view-only pin's region [x, y, w, h] as fractions of the page, checked more strictly than a LaTeX pin's
    frac since it is the pin's only location: 4 finite numbers, inside the page (0..1), with positive area."""
    if not isinstance(fr, list) or len(fr) != 4:
        return InputRejected("frac 은 숫자 4개 목록 [x, y, w, h](쪽 대비 비율)입니다.", "bad_frac")
    nums: list[float] = []
    for v in fr:
        n = num_field(v, "frac")
        if isinstance(n, InputRejected):
            return n
        nums.append(n)
    x, y, w, h = nums
    eps = 1e-6
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 + eps and 0 < h <= 1 + eps
            and x + w <= 1 + eps and y + h <= 1 + eps):
        return InputRejected("frac 이 쪽 밖입니다(0..1, 넓이 > 0).", "frac_outside_page")
    return [x, y, w, h]


def parse_region(d: Json, facts: DocumentFacts) -> dict[str, Any] | InputRejected:
    """A pin location on a view-only PDF document: {pdf, name, kind: "region", page, frac, quote?, pdf_build?}.

    file, lo, hi and scope are refused - such a pin has no lines. page is checked against the page count of the build
    the request names (pdf_build) or the current one (facts.page_count); with no pages yet, any page >= 1 passes.
    quote is whitespace-normalized and truncated to PDF_QUOTE_MAX.
    """
    for k in ("file", "lo", "hi", "scope"):
        if d.get(k) is not None:
            return InputRejected("보기 전용 문서(%s)의 핀에는 %s 가 없습니다 — 쪽(page)과 영역(frac)만 받습니다." % (facts.key, k), "no_source_lines")
    out: dict[str, Any] = {"pdf": str(facts.pdf), "name": facts.pdf.name, "kind": "region"}
    page = int_field(d.get("page"), "page")
    if isinstance(page, InputRejected):
        return page
    want = d.get("pdf_build")
    if want is not None and not valid_build_name(want):
        return InputRejected(PDF_BUILD_REFUSAL, "bad_pdf_build")
    n = facts.page_count(want)
    if page < 1 or (n and page > n):
        return InputRejected("page 는 1..%d 이어야 합니다." % max(n, 1), "page_out_of_range")
    out["page"] = page
    frac = parse_frac(d.get("frac"))
    if isinstance(frac, InputRejected):
        return frac
    out["frac"] = frac
    if d.get("quote") is not None:
        if not isinstance(d["quote"], str):
            return InputRejected("quote 는 문자열입니다.", "bad_quote")
        out["quote"] = truncate_quote(norm(d["quote"]), PDF_QUOTE_MAX)
    if want is not None:
        out["pdf_build"] = want
    return out


def parse_add(d: Json, known: Collection[str], facts: DocumentFacts) -> AddRequest | InputRejected:
    """A POST /api/pin body for the request's document -> the new pin's validated place and fields, or the first field
    refused, in the contract's order: the location first (parse_region on a view-only document, which refuses
    file/lo/hi/scope; parse_loc otherwise, which reads the named file), then note, kind_req, mention hints and
    assignee (known: the logins from server.assignee_people())."""
    region = facts.is_pdf
    named: dict[str, Any]
    fields: dict[str, Any] | InputRejected
    if region:
        named = {k: d[k] for k in REGION_FIELDS + ("file", "lo", "hi", "scope") if k in d}
        fields = parse_region(named, facts)
    else:
        named = {k: d[k] for k in ADD_FIELDS if k in d}
        fields = parse_loc(named, facts)
    if isinstance(fields, InputRejected):
        return fields
    note = parse_note(d.get("note"))
    if isinstance(note, InputRejected):
        return note
    kind_req = parse_kind_req(d.get("kind_req"))
    if isinstance(kind_req, InputRejected):
        return kind_req
    hints = parse_mention_hints(d.get("mentions"))
    if isinstance(hints, InputRejected):
        return hints
    assignee = parse_assignee(d.get("assignee"), known)
    if isinstance(assignee, InputRejected):
        return assignee
    place: Place = RegionPlace(fields) if region else LinePlace(fields, frozenset(named))
    return AddRequest(place, note, kind_req, assignee, tuple(hints))


@dataclass(frozen=True)
class EditBody:
    """An edit body with every field checked except loc, which is checked against the pin's own document once the
    pin is known (parse_edit_place). request.place is still None."""
    loc: Json | None
    request: EditRequest


def parse_edit(d: Json, known: Collection[str]) -> EditBody | InputRejected:
    """A POST /api/pins/{id}/edit body -> its checked fields, or the first one refused, in the contract's order.

    note (null is the empty note), note_append (a non-blank string of at most 2000 characters), loc (an object),
    lo/hi (integers), scope, kind, kind_req, mention hints and assignee (known: the logins from assignee_people()).
    base_rev is required unless the edit is a note_append, and something must be changed.
    """
    note: str | None = None
    if "note" in d:
        parsed = parse_note(d.get("note"))
        if isinstance(parsed, InputRejected):
            return parsed
        note = parsed
    note_append = d.get("note_append")
    if note_append is not None:
        if not isinstance(note_append, str):
            return InputRejected("note_append 는 문자열이어야 합니다.", "bad_note_append")
        if not note_append.strip():
            return InputRejected("덧붙일 메모가 비어 있습니다.", "note_append_empty")
        if len(note_append) > 2000:
            return InputRejected("덧붙일 메모가 너무 깁니다(2000자 이하).", "note_append_too_long")
    loc = d.get("loc")
    if loc is not None and not isinstance(loc, dict):
        return InputRejected("loc 는 객체여야 합니다.", "bad_loc")
    lo = int_field(d["lo"], "lo") if d.get("lo") is not None else None
    if isinstance(lo, InputRejected):
        return lo
    hi = int_field(d["hi"], "hi") if d.get("hi") is not None else None
    if isinstance(hi, InputRejected):
        return hi
    scope = d.get("scope")
    if scope is not None and scope not in SCOPES:
        return InputRejected("scope 는 %s 중 하나입니다." % "|".join(SCOPES), "bad_scope")
    kind = d.get("kind")
    if kind is not None and (not isinstance(kind, str) or len(kind) > 80):
        return InputRejected("kind 가 올바르지 않습니다.", "bad_kind")
    kind_req = parse_kind_req(d.get("kind_req"))   # a note-level value that can be changed even on a closed pin
    if isinstance(kind_req, InputRejected):
        return kind_req
    hints = parse_mention_hints(d.get("mentions"))
    if isinstance(hints, InputRejected):
        return hints
    assignee = parse_assignee(d.get("assignee"), known)   # like kind_req, changeable on a closed pin (leaves an ev=assign)
    if isinstance(assignee, InputRejected):
        return assignee
    base_given = "base_rev" in d
    if not base_given and note_append is None:
        return InputRejected("base_rev 가 필요합니다(카드를 열 때 받은 rev).", "base_rev_required")
    base = int_field(d["base_rev"], "base_rev") if base_given else None
    if isinstance(base, InputRejected):
        return base
    moves = loc is not None or lo is not None or hi is not None
    if not (note is not None or moves or scope is not None or kind is not None or note_append is not None
            or kind_req is not None or assignee is not None):
        return InputRejected("바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).", "nothing_to_change")
    return EditBody(loc, EditRequest(base, note, note_append, None, lo, hi, scope, kind, kind_req, assignee,
                                     tuple(hints)))


def parse_edit_place(body: EditBody, region: bool, facts: DocumentFacts) -> Place | None | InputRejected:
    """An edit's re-placement checked against the pin's own document (facts), or None when the edit sends no loc.

    A view-only pin (region) refuses lo/hi/scope/kind first. Then loc is parsed like a new pin's location (parse_region
    for a view-only pin, parse_loc for a line pin). pdf_build records which build frac's coordinates belong to, so a
    loc that re-places frac takes the one sent or the build on screen, and a loc without frac cannot change it."""
    request = body.request
    if region and (request.lo is not None or request.hi is not None or request.scope is not None
                   or request.kind is not None):
        return InputRejected(REGION_EDIT_REFUSAL, "no_source_lines")
    loc = body.loc
    if loc is None:
        return None
    fields = parse_region(loc, facts) if region else parse_loc(loc, facts)
    if isinstance(fields, InputRejected):
        return fields
    if "frac" in loc:
        fields.setdefault("pdf_build", facts.current_build())
    else:
        fields.pop("pdf_build", None)
    return RegionPlace(fields) if region else LinePlace(fields, frozenset(loc))


class SourceRange(NamedTuple):
    """A validated range of a manuscript file: the file, its lines as read, and 1 <= lo <= hi <= len(lines)."""
    file: Path
    lines: list[str]
    lo: int
    hi: int


def parse_source_range(q: Query, facts: DocumentFacts) -> SourceRange | InputRejected:
    """?file=&lo=&hi= of GET /api/snippet and /api/overlaps: a file in the tree (source_file), whose lines are read
    before lo and hi are parsed as integers (int() of the text) and checked against them."""
    f = source_file(_first(q, "file", ""), facts.root)
    if isinstance(f, InputRejected):
        return f
    lines = facts.lines(f)
    try:
        lo = int(_first(q, "lo", "") or "")
        hi = int(_first(q, "hi", "") or "")
    except ValueError:
        return InputRejected("lo·hi 는 정수여야 합니다.", "not_integer")
    if not 1 <= lo <= hi <= len(lines):
        return InputRejected("줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (len(lines), lo, hi), "range_outside_file")
    return SourceRange(f, lines, lo, hi)


def parse_snippet(q: Query, facts: DocumentFacts) -> SourceRange | InputRejected:
    """GET /api/snippet: refused for a view-only document (it has no source lines), else parse_source_range."""
    if facts.is_pdf:
        return InputRejected("보기 전용 문서(%s)에는 원문 줄이 없습니다." % facts.key, "no_source_lines")
    return parse_source_range(q, facts)


class PickRequest(NamedTuple):
    """A validated selection: the page directory it is traced in, the page (1-based), the box (x0, y0, x1, y1) in points
    clamped to the page, the page size (width, height) in points, and the viewer's frac as sent (None if absent)."""
    pdir: Path
    page: int
    box: tuple[float, float, float, float]
    size: tuple[float, float]
    frac: list[float] | None


@dataclass(frozen=True)
class PickBuildGone:
    """The selection names a page directory that is gone: the viewer re-reads /api/meta and asks again (a 200)."""


def parse_pick(d: Json, facts: DocumentFacts) -> PickRequest | PickBuildGone | InputRejected:
    """A POST /api/pick body, in the order the server has always checked it: pdf_build (the build on screen at drag
    time) must be a page directory name, and a gone one is answered at once; then page within that build's pages,
    x0, x1, y0, y1 as finite numbers (clamped to the page), and frac, when sent, as four finite numbers."""
    want = d.get("pdf_build")
    if want is not None and not valid_build_name(want):
        return InputRejected(PDF_BUILD_REFUSAL, "bad_pdf_build")
    found = facts.pick_pages(want)
    if found is None:
        return PickBuildGone()
    pdir, pages = found
    page = int_field(d.get("page"), "page")
    if isinstance(page, InputRejected):
        return page
    if not 1 <= page <= len(pages):
        return InputRejected("page 는 1..%d 이어야 합니다." % len(pages), "page_out_of_range")
    pw, ph = pages[page - 1]
    clamped: list[float] = []
    for k, top in (("x0", pw), ("x1", pw), ("y0", ph), ("y1", ph)):
        v = num_field(d.get(k), k)
        if isinstance(v, InputRejected):
            return v
        clamped.append(min(max(v, 0.0), top))
    x0, x1 = sorted(clamped[:2])
    y0, y1 = sorted(clamped[2:])
    frac = d.get("frac")
    if frac is not None and not (isinstance(frac, list) and len(frac) == 4 and
                                 all(not isinstance(v, bool) and isinstance(v, (int, float))
                                     and math.isfinite(v) for v in frac)):
        return InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac")
    return PickRequest(pdir, page, (x0, y0, x1, y1), (pw, ph), frac)

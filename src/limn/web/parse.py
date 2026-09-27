"""Request parsing for routes still owned by web, checked once at the boundary (R3).

Each parser returns the value the service takes, or an InputRejected carrying the exact 400 message and reason of the
agent contract (docs/handbook/api.md §오류 응답); the handler answers a refusal with web.answers.accepted(). Parsers
never raise for bad input. When a request is refused for several fields, the first one in the order the server has
always checked them is the one answered, so each parser keeps that order.

Most parsers look at the request alone. The location parsers of a new pin, an edit's re-placement, a selection and
a snippet also check the request against the manuscript - that a named file lies in the tree, that lines lie in the
file, that a page is in the build. They read those facts through DocumentFacts, which the composition root
(server.document_facts) supplies for the request's document; nothing here reads a file itself, apart from resolving
a named path against the tree (limn.files.file_in_tree). Close and reopen input belongs to the pin lifecycle feature.
"""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol, TypeAlias

from limn.build import valid_build_name
from limn.files import BadPath, NotAFile, OutsideTree, file_in_tree
from limn.mapping import norm, truncate_quote
from limn.pins.edit import (
    ASSIGNEE_AGENT,
    LOCAL_LOGIN,
    NOTE_MAX,
    PDF_QUOTE_MAX,
    SCOPES,
    AddRequest,
    EditRequest,
    LinePlace,
    Place,
    RegionPlace,
    Scope,
    is_scope,
)
from limn.pins.model import KIND_REQS, KindReq, Record, is_kind_req
from limn.pins.shapes import is_finite_num, is_int
from limn.revisions import REVISION_ID_RE
from limn.web.errors import InputRejected

Json: TypeAlias = Mapping[str, Any]  # a request's JSON object
Query: TypeAlias = Mapping[str, list[str]]  # parse_qs() of a query string

CLAIM_TTL_DEFAULT = 120  # minutes - lock duration used when neither ttl_min nor eta_min is given for a claim (docs/handbook/api.md §처리 중 표시 (claim))
CLAIM_TTL_MIN = 1
# the lock auto-expiring is a safety net - at 480 a stuck agent held a pin for half a day (observed 23 times)
CLAIM_TTL_MAX = 120
CLAIM_ETA_MIN = 1  # minutes - estimated time to handle (eta_min). Shown in the UI rounded up to 5-minute steps
CLAIM_ETA_MAX = 240
CLAIM_TTL_FLOOR = 30  # if only eta_min is given, the lock is min(ceiling, max(this floor, eta x 2)) - even a short estimate holds for 30 min
# one reply - like the note (NOTE_MAX), only string/length are checked; the UI renders it via esc()
THREAD_TEXT_MAX = 1000
MENTION_MAX = 10  # cap on mention hints per post
ADD_FIELDS = (
    "file",
    "name",
    "page",
    "lo",
    "hi",
    "raw_lo",
    "raw_hi",
    "kind",
    "via",
    "score",
    "frac",
    "note",
    "scope",
    "quote",
    "pdf_build",
)
REGION_FIELDS = ("page", "frac", "note", "quote", "pdf_build")
REGION_EDIT_REFUSAL = "보기 전용 문서의 핀에는 줄 범위가 없습니다 — 메모(note)와 영역(loc: page, frac)만 고칩니다."
PDF_BUILD_REFUSAL = "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다."
REVISION_BUILD_FIELDS = frozenset({"commit", "doc", "pin"})
# The phrase POST /api/clear must carry as its body's `confirm` before every pin is archived and cleared.
CLEAR_CONFIRM = "clear all pins"

Frac: TypeAlias = tuple[float, float, float, float]  # a selection's [x, y, w, h] as fractions of its page
Via: TypeAlias = Literal["synctex", "text"]  # how the viewer traced a line pin's range


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

    @property
    def state(self) -> Path:
        """The instance's state folder, never part of the tree even when it lies inside root (limn.files.tree_part)."""
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


def _is_str_list(v: object) -> bool:
    """A JSON list of strings."""
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _first(q: Query, key: str, default: str | None = None) -> str | None:
    """The first value of query parameter `key`, or default when the query has none."""
    values = q.get(key)
    return values[0] if values else default


def parse_flag(q: Query, name: str) -> bool:
    """A query-string switch (?log=1, ?async=1, ?all=1, ?light=1, ?levels=1): on only when its first value is exactly
    "1"; absent, "0", "true" or anything else is off. Never refused."""
    return _first(q, name, "0") == "1"


def int_field(v: object, what: str) -> int | InputRejected:
    """An integral JSON number (1 and 1.0 both give 1; a bool, NaN or 1.5 does not) named `what` in the refusal."""
    if not is_finite_num(v) or int(v) != v:
        return InputRejected("%s 는 정수여야 합니다." % what, "not_integer")
    return int(v)


def num_field(v: object, what: str) -> float | InputRejected:
    """A finite JSON number other than a bool, as a float, named `what` in the refusal."""
    if not is_finite_num(v):
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


def parse_kind_req(v: object) -> KindReq | None | InputRejected:
    """Pin kind - 'fix' (fix request) | 'question'. None if absent (= fix, same as a legacy pin)."""
    if v is None:
        return None
    if not isinstance(v, str) or not is_kind_req(v):
        return InputRejected("kind_req 는 %s 중 하나입니다." % "|".join(KIND_REQS), "bad_kind_req")
    return v


def parse_scope(v: object) -> Scope | None | InputRejected:
    """A line pin's range-ladder rung (SCOPES), or None when absent."""
    if v is None:
        return None
    if not is_scope(v):
        return InputRejected("scope 는 %s 중 하나입니다." % "|".join(SCOPES), "bad_scope")
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
        return InputRejected(
            "담당(assignee) '%s' 은(는) 이 뷰어가 아는 사람이 아닙니다 — 'agent' 또는 뷰어를 연 적 있는 테일넷 사람의 로그인을 쓰세요."
            % v,
            "unknown_assignee",
        )
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
    if not is_finite_num(v) or int(v) != v:
        return InputRejected("%s 은 정수여야 합니다." % key, "not_integer")
    n = int(v)
    if n < lo:
        return InputRejected(
            "%s 은 %d 이상이어야 합니다(상한 %d 를 넘으면 %d 로 깎아 받습니다)." % (key, lo, hi, hi), "too_small"
        )
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
    if isinstance(v, int) and is_int(v) and 1 <= v <= 999999999:
        return v
    return InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin")


class RevisionQuery(NamedTuple):
    """A revision request's commit (a full lowercase SHA-1) and optional pin."""

    commit: str
    pin: int | None


def parse_commit(v: object) -> str | InputRejected:
    """A commit id as the revision routes take it: a full lowercase SHA-1 string. Whether it is one of the document's
    recent commits is the service's to decide."""
    if not isinstance(v, str) or not REVISION_ID_RE.fullmatch(v):
        return InputRejected("올바른 커밋 ID가 아닙니다.", "bad_commit")
    return v


def parse_revision_query(q: Query) -> RevisionQuery | InputRejected:
    """GET /api/revision-diff|-build|-pdf: the optional &pin= (parse_pin_param) first, then ?commit= (parse_commit)."""
    pin = parse_pin_param(_first(q, "pin"))
    if isinstance(pin, InputRejected):
        return pin
    commit = parse_commit(_first(q, "commit", "") or "")
    if isinstance(commit, InputRejected):
        return commit
    return RevisionQuery(commit, pin)


def parse_revision_build(d: Json) -> RevisionQuery | InputRejected:
    """POST /api/revision-build's body: only commit, doc and pin; pin, when present, a JSON integer in range; then
    the commit (parse_commit)."""
    if set(d) - REVISION_BUILD_FIELDS:
        return InputRejected("허용되지 않는 비교 PDF 요청 필드입니다.", "unknown_fields")
    if "pin" in d and not is_int(d["pin"]):
        return InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin")
    pin = parse_pin_param(d.get("pin"))
    if isinstance(pin, InputRejected):
        return pin
    commit = parse_commit(d.get("commit"))
    if isinstance(commit, InputRejected):
        return commit
    return RevisionQuery(commit, pin)


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


class DocChoice(NamedTuple):
    """How a request names its document, parsed: key is ?doc= or the body's doc, which agree (parse_doc_key; None
    when neither names one). A POST /api/pin also carries file_hint, the body's file as sent - with no key the
    document holding it is chosen, and a value that is no file simply matches none - and body_key, the body's doc
    when it is a string, which wins over ?doc= as it always has ("" naming the first document)."""

    key: str | None
    file_hint: object = None
    body_key: str | None = None


def parse_doc_choice(q: Query | None, body: Json | None = None, new_pin: bool = False) -> DocChoice | InputRejected:
    """The document a request names (parse_doc_key: 400 bad_doc or doc_mismatch), and for a new pin (new_pin, POST
    /api/pin) the body's file hint and its own doc. Whether a key names a document is the server's to decide."""
    key = parse_doc_key(q, body)
    if isinstance(key, InputRejected):
        return key
    if not new_pin or body is None:
        return DocChoice(key)
    want = body.get("doc")
    return DocChoice(key, body.get("file"), want if isinstance(want, str) else None)


def parse_events_query(q: Query) -> int | None | InputRejected:
    """GET /api/meta's ?ev= (parse_event_cursor on its first value)."""
    return parse_event_cursor(_first(q, "ev"))


class PinsQuery(NamedTuple):
    """GET /api/pins: every pin including closed ones (?all=1), and whether ?doc= names a document, which keeps only
    that document's pins."""

    all: bool
    doc_scoped: bool


def parse_pins_query(q: Query) -> PinsQuery:
    """GET /api/pins's switches; never refused (a ?doc= naming no document was refused when the document was found)."""
    return PinsQuery(parse_flag(q, "all"), bool(q.get("doc")))


class RebuildQuery(NamedTuple):
    """POST /api/rebuild's switches: keep the whole log in the answer (?log=1), and build in the background (?async=1)."""

    full_log: bool
    background: bool


def parse_rebuild_query(q: Query) -> RebuildQuery:
    """POST /api/rebuild's switches (parse_flag); never refused."""
    return RebuildQuery(parse_flag(q, "log"), parse_flag(q, "async"))


def parse_build_name(q: Query) -> str:
    """GET /pdf's ?build= as sent, "" when absent (the build on screen). Never refused: a name that is not a page
    directory simply has no PDF (limn.build.build_pdf)."""
    return _first(q, "build", "") or ""


@dataclass(frozen=True)
class ClearConfirmed:
    """A POST /api/clear body that carries the confirmation phrase (CLEAR_CONFIRM)."""


def parse_clear(d: Json) -> ClearConfirmed | InputRejected:
    """A POST /api/clear body: its confirm must be exactly CLEAR_CONFIRM, else 400 confirm_required naming the phrase
    and the archive left behind. Any other field is ignored."""
    if d.get("confirm") != CLEAR_CONFIRM:
        return InputRejected(
            '모든 핀을 지우려면 본문에 {"confirm": "%s"} 를 보내세요(보관본 pins_<시각>.jsonl.bak 이 남습니다).'
            % CLEAR_CONFIRM,
            "confirm_required",
        )
    return ClearConfirmed()


def source_file(p: object, root: Path, state: Path) -> Path | InputRejected:
    """The real file inside the manuscript tree root that p names (absolute, or relative to the tree), or why not
    (limn.files.file_in_tree): a bad value, a file outside the tree (the state folder `state` included), or no such
    file."""
    match file_in_tree(p, root, state):
        case Path() as f:
            return f
        case BadPath():
            return InputRejected("file 이 올바르지 않습니다.", "bad_file")
        case OutsideTree():
            return InputRejected("원고 디렉토리 밖의 파일입니다: %s" % p, "file_outside_manuscript")
        case NotAFile():
            return InputRejected("원고 안에 그런 파일이 없습니다: %s" % p, "file_not_found")


@dataclass(frozen=True)
class LineLoc:
    """A line pin's checked location (parse_loc): the file inside the manuscript tree (absolute, resolved) and its
    name, the range 1 <= lo <= hi <= the file's line count, the page (>= 1), and each optional field the request sent
    - None when it did not."""

    file: str
    name: str
    lo: int
    hi: int
    page: int
    raw_lo: int | None = None
    raw_hi: int | None = None
    kind: str | None = None
    via: Via | None = None
    score: float | None = None
    frac: Frac | None = None
    scope: Scope | None = None
    quote: str | None = None
    pdf_build: str | None = None

    def to_record(self) -> Record:
        """The fields as a pin record stores them: file, name, lo, hi, page, then each optional field that was sent,
        in this order (the key order pin records have always had; frac as a JSON list)."""
        out: dict[str, Any] = {"file": self.file, "name": self.name, "lo": self.lo, "hi": self.hi, "page": self.page}
        optional: tuple[tuple[str, object], ...] = (
            ("raw_lo", self.raw_lo),
            ("raw_hi", self.raw_hi),
            ("kind", self.kind),
            ("via", self.via),
            ("score", self.score),
            ("frac", None if self.frac is None else list(self.frac)),
            ("scope", self.scope),
            ("quote", self.quote),
            ("pdf_build", self.pdf_build),
        )
        out.update((k, v) for k, v in optional if v is not None)
        return out


@dataclass(frozen=True)
class RegionLoc:
    """A view-only pin's checked location (parse_region): the document's PDF and its name, the page (within the
    build's pages when it has any), the region frac inside the page, and the optional quote (normalized and cut) and
    pdf_build - None when not sent."""

    pdf: str
    name: str
    page: int
    frac: Frac
    quote: str | None = None
    pdf_build: str | None = None

    def to_record(self) -> Record:
        """The fields as a pin record stores them: pdf, name, kind "region", page, frac (a JSON list), then quote and
        pdf_build when present - the key order region pins have always had."""
        out: dict[str, Any] = {
            "pdf": self.pdf,
            "name": self.name,
            "kind": "region",
            "page": self.page,
            "frac": list(self.frac),
        }
        if self.quote is not None:
            out["quote"] = self.quote
        if self.pdf_build is not None:
            out["pdf_build"] = self.pdf_build
        return out


def _frac4(v: object, refusal: InputRejected) -> Frac | InputRejected:
    """Four finite JSON numbers as a Frac, or the first one's num_field refusal; `refusal` when v is not a list of
    exactly four."""
    if not isinstance(v, list) or len(v) != 4:
        return refusal
    nums: list[float] = []
    for x in v:
        n = num_field(x, "frac")
        if isinstance(n, InputRejected):
            return n
        nums.append(n)
    return nums[0], nums[1], nums[2], nums[3]


def parse_loc(d: Json, facts: DocumentFacts) -> LineLoc | InputRejected:
    """A line pin's location, or the first field refused.

    file must be a file inside the manuscript tree and 1 <= lo <= hi <= its line count, so this reads that file's
    lines (facts.lines) before checking the range. page defaults to 1; raw_lo, raw_hi, kind, via, score, frac, scope,
    quote (truncated to 60 characters) and pdf_build (a page directory name) are checked in that order when sent (a
    null counts as not sent). The checked location is constructed only after every field has passed.
    """
    f = source_file(d.get("file"), facts.root, facts.state)
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
    page = int_field(d.get("page", 1), "page")
    if isinstance(page, InputRejected):
        return page
    if page < 1:
        return InputRejected("page 는 1 이상이어야 합니다.", "bad_page")
    raw: dict[str, int] = {}
    for k in ("raw_lo", "raw_hi"):
        if d.get(k) is not None:
            v = int_field(d[k], k)
            if isinstance(v, InputRejected):
                return v
            raw[k] = v
    kind = d.get("kind")
    if kind is not None and (not isinstance(kind, str) or len(kind) > 80):
        return InputRejected("kind 가 올바르지 않습니다.", "bad_kind")
    via = d.get("via")
    if via is not None and via not in ("synctex", "text"):
        return InputRejected("via 는 synctex|text 입니다.", "bad_via")
    score = d.get("score")
    if score is not None:
        score = num_field(score, "score")
        if isinstance(score, InputRejected):
            return score
    frac = d.get("frac")
    if frac is not None:
        frac = _frac4(frac, InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac"))
        if isinstance(frac, InputRejected):
            return frac
    scope = d.get("scope")
    if scope is not None:
        scope = parse_scope(scope)
        if isinstance(scope, InputRejected):
            return scope
    quote = d.get("quote")
    if quote is not None:
        if not isinstance(quote, str):
            return InputRejected("quote 는 문자열입니다.", "bad_quote")
        quote = truncate_quote(quote, 60)
    pdf_build = d.get("pdf_build")  # the build on screen at drag time (pdf_build from the pick response)
    if pdf_build is not None and not valid_build_name(pdf_build):
        return InputRejected(PDF_BUILD_REFUSAL, "bad_pdf_build")
    return LineLoc(
        file=str(f),
        name=f.name,
        lo=lo,
        hi=hi,
        page=page,
        raw_lo=raw.get("raw_lo"),
        raw_hi=raw.get("raw_hi"),
        kind=kind,
        via=via,
        score=score,
        frac=frac,
        scope=scope,
        quote=quote,
        pdf_build=pdf_build,
    )


def parse_frac(fr: object) -> Frac | InputRejected:
    """A view-only pin's region [x, y, w, h] as fractions of the page, checked more strictly than a LaTeX pin's
    frac since it is the pin's only location: 4 finite numbers, inside the page (0..1), with positive area."""
    frac = _frac4(fr, InputRejected("frac 은 숫자 4개 목록 [x, y, w, h](쪽 대비 비율)입니다.", "bad_frac"))
    if isinstance(frac, InputRejected):
        return frac
    x, y, w, h = frac
    eps = 1e-6
    if not (
        0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 + eps and 0 < h <= 1 + eps and x + w <= 1 + eps and y + h <= 1 + eps
    ):
        return InputRejected("frac 이 쪽 밖입니다(0..1, 넓이 > 0).", "frac_outside_page")
    return frac


def parse_region(d: Json, facts: DocumentFacts) -> RegionLoc | InputRejected:
    """A pin location on a view-only PDF document (the document's own PDF), or the first field refused.

    file, lo, hi and scope are refused - such a pin has no lines. page is checked against the page count of the build
    the request names (pdf_build) or the current one (facts.page_count); with no pages yet, any page >= 1 passes.
    quote is whitespace-normalized and truncated to PDF_QUOTE_MAX.
    """
    for k in ("file", "lo", "hi", "scope"):
        if d.get(k) is not None:
            return InputRejected(
                "보기 전용 문서(%s)의 핀에는 %s 가 없습니다 — 쪽(page)과 영역(frac)만 받습니다." % (facts.key, k),
                "no_source_lines",
            )
    pdf = facts.pdf
    page = int_field(d.get("page"), "page")
    if isinstance(page, InputRejected):
        return page
    want = d.get("pdf_build")
    if want is not None and not valid_build_name(want):
        return InputRejected(PDF_BUILD_REFUSAL, "bad_pdf_build")
    n = facts.page_count(want)
    if page < 1 or (n and page > n):
        return InputRejected("page 는 1..%d 이어야 합니다." % max(n, 1), "page_out_of_range")
    frac = parse_frac(d.get("frac"))
    if isinstance(frac, InputRejected):
        return frac
    quote: str | None = None
    if d.get("quote") is not None:
        if not isinstance(d["quote"], str):
            return InputRejected("quote 는 문자열입니다.", "bad_quote")
        quote = truncate_quote(norm(d["quote"]), PDF_QUOTE_MAX)
    return RegionLoc(str(pdf), pdf.name, page, frac, quote, want)


def parse_add(d: Json, known: Collection[str], facts: DocumentFacts) -> AddRequest | InputRejected:
    """A POST /api/pin body for the request's document -> the new pin's validated place and fields, or the first field
    refused, in the contract's order: the location first (parse_region on a view-only document, which refuses
    file/lo/hi/scope; parse_loc otherwise, which reads the named file), then note, kind_req, mention hints and
    assignee (known: the logins from server.assignee_people())."""
    place: Place
    if facts.is_pdf:
        region = parse_region({k: d[k] for k in REGION_FIELDS + ("file", "lo", "hi", "scope") if k in d}, facts)
        if isinstance(region, InputRejected):
            return region
        place = RegionPlace(region.to_record())
    else:
        named = {k: d[k] for k in ADD_FIELDS if k in d}
        line = parse_loc(named, facts)
        if isinstance(line, InputRejected):
            return line
        place = LinePlace(line.to_record(), frozenset(key for key, value in named.items() if value is not None))
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
    scope = parse_scope(d.get("scope"))
    if isinstance(scope, InputRejected):
        return scope
    kind = d.get("kind")
    if kind is not None and (not isinstance(kind, str) or len(kind) > 80):
        return InputRejected("kind 가 올바르지 않습니다.", "bad_kind")
    kind_req = parse_kind_req(d.get("kind_req"))  # a note-level value that can be changed even on a closed pin
    if isinstance(kind_req, InputRejected):
        return kind_req
    hints = parse_mention_hints(d.get("mentions"))
    if isinstance(hints, InputRejected):
        return hints
    # like kind_req, changeable on a closed pin (leaves an ev=assign)
    assignee = parse_assignee(d.get("assignee"), known)
    if isinstance(assignee, InputRejected):
        return assignee
    base_given = "base_rev" in d
    if not base_given and note_append is None:
        return InputRejected("base_rev 가 필요합니다(카드를 열 때 받은 rev).", "base_rev_required")
    base = int_field(d["base_rev"], "base_rev") if base_given else None
    if isinstance(base, InputRejected):
        return base
    moves = loc is not None or lo is not None or hi is not None
    if not (
        note is not None
        or moves
        or scope is not None
        or kind is not None
        or note_append is not None
        or kind_req is not None
        or assignee is not None
    ):
        return InputRejected(
            "바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).", "nothing_to_change"
        )
    return EditBody(
        loc, EditRequest(base, note, note_append, None, lo, hi, scope, kind, kind_req, assignee, tuple(hints))
    )


def parse_edit_place(body: EditBody, region: bool, facts: DocumentFacts) -> Place | None | InputRejected:
    """An edit's re-placement checked against the pin's own document (facts), or None when the edit sends no loc.

    A view-only pin (region) refuses lo/hi/scope/kind first. Then loc is parsed like a new pin's location (parse_region
    for a view-only pin, parse_loc for a line pin). pdf_build records which build frac's coordinates belong to, so a
    loc that re-places frac takes the one sent or the build on screen, and a loc without frac cannot change it."""
    request = body.request
    if region and (
        request.lo is not None or request.hi is not None or request.scope is not None or request.kind is not None
    ):
        return InputRejected(REGION_EDIT_REFUSAL, "no_source_lines")
    loc = body.loc
    if loc is None:
        return None
    if region:
        area = parse_region(loc, facts)
        if isinstance(area, InputRejected):
            return area
        return RegionPlace(replace(area, pdf_build=_placed_build(loc, area.pdf_build, facts)).to_record())
    line = parse_loc(loc, facts)
    if isinstance(line, InputRejected):
        return line
    return LinePlace(
        replace(line, pdf_build=_placed_build(loc, line.pdf_build, facts)).to_record(),
        frozenset(key for key, value in loc.items() if value is not None),
    )


def _placed_build(loc: Json, sent: str | None, facts: DocumentFacts) -> str | None:
    """The pdf_build an edit's re-placement records: the one sent, else the build on screen, when loc re-places frac
    (its coordinates belong to that build); None - the pin's own is kept - when loc sends no frac."""
    if loc.get("frac") is None:
        return None
    current = facts.current_build()  # read even when one was sent, as it always has been
    return sent if sent is not None else current


class SourceRange(NamedTuple):
    """A validated range of a manuscript file: the file, its lines as read, and 1 <= lo <= hi <= len(lines)."""

    file: Path
    lines: list[str]
    lo: int
    hi: int


def parse_source_range(q: Query, facts: DocumentFacts) -> SourceRange | InputRejected:
    """?file=&lo=&hi= of GET /api/snippet and /api/overlaps: a file in the tree (source_file), whose lines are read
    before lo and hi are parsed as integers (int() of the text) and checked against them."""
    f = source_file(_first(q, "file", ""), facts.root, facts.state)
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
    if frac is not None and not (isinstance(frac, list) and len(frac) == 4 and all(is_finite_num(v) for v in frac)):
        return InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac")
    return PickRequest(pdir, page, (x0, y0, x1, y1), (pw, ph), frac)

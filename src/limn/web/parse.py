"""Request parsing for routes still owned by web, checked once at the boundary (R3).

Each parser returns the value the service takes, or an InputRejected carrying the exact 400 message and reason of the
agent contract (docs/handbook/api.md §오류 응답); the handler answers a refusal with web.answers.accepted(). Parsers
never raise for bad input. When a request is refused for several fields, the first one in the order the server has
always checked them is the one answered, so each parser keeps that order.

Most parsers look at the request alone. The PDF selection and source-range parsers live in the location feature. They
read manuscript and build facts through DocumentFacts, which the composition root
(server.document_facts) supplies for the request's document; nothing here reads a file itself, apart from resolving
a named path against the tree (limn.files.file_in_tree). Close and reopen input belongs to the pin lifecycle feature.
"""

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol, TypeAlias

from limn.files import BadPath, NotAFile, OutsideTree, file_in_tree
from limn.pins.edit import (
    ASSIGNEE_AGENT,
    LOCAL_LOGIN,
    NOTE_MAX,
    SCOPES,
    Scope,
    is_scope,
)
from limn.pins.model import KIND_REQS, KindReq, is_kind_req
from limn.pins.shapes import is_finite_num
from limn.web.errors import InputRejected

Json: TypeAlias = Mapping[str, Any]  # a request's JSON object
Query: TypeAlias = Mapping[str, list[str]]  # parse_qs() of a query string

# one reply - like the note (NOTE_MAX), only string/length are checked; the UI renders it via esc()
THREAD_TEXT_MAX = 1000
MENTION_MAX = 10  # cap on mention hints per post
PDF_BUILD_REFUSAL = "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다."

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


def query_first(q: Query, key: str, default: str | None = None) -> str | None:
    """The first value of query parameter `key`, or default when the query has none."""
    values = q.get(key)
    return values[0] if values else default


def parse_flag(q: Query, name: str) -> bool:
    """A query-string switch (?log=1, ?async=1, ?all=1, ?light=1, ?levels=1): on only when its first value is exactly
    "1"; absent, "0", "true" or anything else is off. Never refused."""
    return query_first(q, name, "0") == "1"


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
    (the editing request collaborators)."""
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


def parse_doc_key(q: Query | None, body: Json | None = None) -> str | None | InputRejected:
    """The document a request names: ?doc= or the body's doc - the two must agree, and the body's must be a string.
    None (or "") when neither names one; which document that means is the server's (server.request_doc)."""
    key = query_first(q, "doc") if q else None
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

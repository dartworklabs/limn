"""HTTP answers for routes still owned by web: one function per route, one `match` per function.

Each function takes the outcome value a server.py shell returned (limn.pins types, PinNotFound, the revision
services' values, a document lookup's DocNotFound) or a request parser returned (InputRejected,
limn.web.parse) and gives the body of the 200 response (with its status where a route has more than one), or raises
HTTPError with the status and body of a refusal; the handler sends the body and its _run turns the HTTPError into the
error response. The handler itself answers only transport refusals (body framing and size, Host/Origin, an unknown
path) and those of the access checks. Statuses, bodies and messages are the agent contract (docs/handbook/api.md). A
record goes out through `show` (server.py's public(), which places the pin's file on this machine), a state name comes
from `state_of` (server.py's pin_state()), and a value a message quotes from the request goes through `text`
(server.py's hdr_text()). Nothing here reads files, the clock or the request.
"""

from collections.abc import Callable
from typing import Any, NoReturn, TypeAlias, TypeVar

from limn.documents import DocNotFound
from limn.pins.model import Record
from limn.revisions import (
    AllSlotsBusy,
    CommitNotRecent,
    DiffFailed,
    DiffUnavailable,
    DocumentBusy,
    NoHistory,
    NoParent,
    NotInRepo,
    RevisionNotReady,
    RevisionPdfMissing,
    RevisionRefusal,
    UnsafeCache,
)
from limn.scope import PinNotInDoc, ScopeMismatch, ScopeUnreadable, ScopeUnwritable, UnsafePath
from limn.web.errors import HTTPError, InputRejected, scope_http_error

Show: TypeAlias = Callable[[Record], object]
StateOf: TypeAlias = Callable[[Record], str]
Text: TypeAlias = Callable[[object], str]
T = TypeVar("T")

CONFIRM_BY_HUMAN = "확인은 사람이 합니다 — 테일넷 신원으로 접속해 뷰어에서 [확인]을 누르세요."


def accepted(value: T | InputRejected) -> T:
    """A request parser's value (limn.web.parse), or the 400 of its refusal: the parser's message, word for word, and
    its reason."""
    if isinstance(value, InputRejected):
        raise HTTPError(400, value.message, reason=value.reason)
    return value


def found_doc(found: T | DocNotFound, text: Text) -> T:
    """The document a request names, or 404 unknown_doc for a key this instance does not serve: the key (through text,
    cut to 40 characters) and every key it does serve (docs)."""
    if isinstance(found, DocNotFound):
        raise HTTPError(404, "없는 문서입니다: %s" % text(found.key)[:40], docs=list(found.known), reason="unknown_doc")
    return found


def revision_refused(result: RevisionRefusal) -> NoReturn:
    """The HTTP answer to every refusal of the revision routes (GET /api/revision-diff|-build|-pdf, POST
    /api/revision-build), with the statuses and bodies of the agent contract; a pin-scoping refusal through
    SCOPE_REJECTIONS."""
    match result:
        case NoHistory():
            raise HTTPError(404, "이 문서는 원고 변경사항을 볼 수 없습니다.", reason="no_history")
        case CommitNotRecent():
            raise HTTPError(404, "현재 문서의 최근 커밋이 아닙니다.", reason="commit_not_recent")
        case DiffFailed():
            raise HTTPError(404, "변경사항을 읽지 못했습니다.", reason="diff_unreadable")
        case DiffUnavailable():
            raise HTTPError(503, "변경사항을 읽지 못했습니다.", reason="diff_unreadable")
        case NotInRepo():
            raise HTTPError(400, "Git 저장소 안의 문서 빌드 루트가 필요합니다.", reason="not_in_repo")
        case NoParent():
            raise HTTPError(422, "첫 커밋은 이전 원고가 없어 비교 PDF를 만들 수 없습니다.", reason="no_parent")
        case AllSlotsBusy():
            raise HTTPError(409, "다른 비교 PDF를 만드는 중입니다. 잠시 뒤 다시 시도하세요.", reason="busy")
        case DocumentBusy():
            raise HTTPError(409, "이 문서의 비교 PDF를 만드는 중입니다.", reason="busy")
        case UnsafeCache():
            raise HTTPError(503, "비교 캐시 경로가 올바르지 않습니다.", reason="unsafe_cache")
        case RevisionNotReady():
            raise HTTPError(404, "해당 비교 PDF가 아직 없거나 만료됐습니다.", reason="revision_not_ready")
        case RevisionPdfMissing():
            raise HTTPError(404, "해당 비교 PDF가 없습니다.", reason="revision_pdf_missing")
        case PinNotInDoc() | ScopeUnreadable() | ScopeMismatch() | UnsafePath() | ScopeUnwritable():
            raise scope_http_error(result)


def revision_answer(result: dict[str, Any] | RevisionRefusal) -> dict[str, Any]:
    """A revision route's JSON body (the source diff, or a comparison build's status), or its refusal's answer."""
    if isinstance(result, dict):
        return result
    revision_refused(result)


def revision_start_answer(result: dict[str, Any] | RevisionRefusal) -> tuple[dict[str, Any], int]:
    """POST /api/revision-build: the comparison build's status with 202 while it is running (just started or already
    under way), 200 once it has an answer (ready or failed); a refusal through revision_refused."""
    body = revision_answer(result)
    return body, 202 if body["state"] == "running" else 200


def revision_pdf_answer(result: bytes | RevisionRefusal) -> bytes:
    """GET /api/revision-pdf: the comparison PDF's bytes, or its refusal's answer."""
    if isinstance(result, bytes):
        return result
    revision_refused(result)

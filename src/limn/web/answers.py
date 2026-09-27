"""HTTP answers for routes still owned by web: one function per route, one `match` per function.

Each function takes the outcome value a server.py shell returned (limn.pins types, PinNotFound, the revision
services' values, limn.build's outcomes, a document lookup's DocNotFound) or a request parser returned (InputRejected,
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

from limn.build import (
    BuildAborted,
    BuildBusy,
    BuildFailed,
    BuildOk,
    BuildOkWithErrors,
    BuildStarted,
    CopyFailed,
    FinishedBuild,
    ViewOnlyNoRebuild,
)
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
from limn.web.errors import HTTPError, InputRejected, build_failure_log, scope_http_error

Body: TypeAlias = dict[str, object]
Show: TypeAlias = Callable[[Record], object]
StateOf: TypeAlias = Callable[[Record], str]
Text: TypeAlias = Callable[[object], str]
T = TypeVar("T")

CONFIRM_BY_HUMAN = "확인은 사람이 합니다 — 테일넷 신원으로 접속해 뷰어에서 [확인]을 누르세요."
# The log lines an agent response keeps for a non-successful build (docs/handbook/build-sync.md §에이전트 응답 다이어트).
LOG_TAIL_LINES = 40


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


def build_pdf_gone(name: str, pages_build: str, text: Text) -> NoReturn:
    """GET /pdf when the build's PDF cannot be served: 404 pdf_build_gone for a named build (?build=, through text and
    cut to 60 characters) that is gone or has no PDF, pdf_missing when none was named - never another build's PDF. The
    body names the build on screen (pages_build) so the viewer falls back to its page images."""
    raise HTTPError(
        404,
        "그 빌드의 PDF 가 없습니다: %s" % text(name)[:60],
        pdf_build_gone=bool(name),
        pages_build=pages_build,
        reason="pdf_build_gone" if name else "pdf_missing",
    )


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


def _last_log_lines(text: object) -> str:
    """The last LOG_TAIL_LINES lines of a log (a missing or empty log reads as "")."""
    return "\n".join(str(text or "").splitlines()[-LOG_TAIL_LINES:])


def diet_log(payload: dict[str, Any], full: bool) -> dict[str, Any]:
    """The build state as GET /api/build answers it (docs/handbook/build-sync.md §에이전트 응답 다이어트): log/log_tail
    are dropped when state=='ok' (even a success ran a few KB via font paths), and for any other state (ok_errors,
    fail, ...) trimmed to their last LOG_TAIL_LINES lines - on a copy. With full (?log=1) payload itself comes back.
    The build state (the document's bstate, builds.json) is never changed: this applies only right before the HTTP response.
    POST /api/rebuild's answer applies the same diet by outcome type (rebuild_answer)."""
    if full:
        return payload
    out = dict(payload)
    state = out.get("state")
    for key in ("log", "log_tail"):
        if key not in out:
            continue
        if state == "ok":
            out.pop(key, None)
        else:
            out[key] = _last_log_lines(out[key])
    return out


def finished_build_body(result: FinishedBuild) -> Body:
    """A finished build as JSON - POST /api/rebuild's body before the log diet, in the key order the agent contract has
    always had: ok, state, errors, log, elapsed_s, then only what the build got as far as - pull (when --git-pull ran),
    src_mtime (a LaTeX build), src_hash (once the copy was fingerprinted), and for new pages head, build, pages. A
    failure's log is limn.web.errors.build_failure_log's text."""
    match result:
        case BuildOk():
            return _new_pages_body(result, "ok", [])
        case BuildOkWithErrors(errors=errors):
            return _new_pages_body(result, "ok_errors", errors)
        case CopyFailed(pull=pull, src_mtime=src_mtime, elapsed_s=elapsed_s):
            body = _failed_body([], build_failure_log(result), elapsed_s)
            _put_source(body, pull, src_mtime)
            return body
        case BuildFailed(errors=errors, pull=pull, src_mtime=src_mtime, src_hash=src_hash, elapsed_s=elapsed_s):
            body = _failed_body(errors, build_failure_log(result), elapsed_s)
            _put_source(body, pull, src_mtime)
            body["src_hash"] = src_hash
            return body
        case BuildAborted():
            return _failed_body([], build_failure_log(result), 0.0)


def _new_pages_body(result: BuildOk | BuildOkWithErrors, state: str, errors: list[Any]) -> Body:
    """The body of a build that made new page images: ok true, its state and errors, the log, then the source keys
    and the new pages (src_hash, head, build, pages)."""
    body: Body = {"ok": True, "state": state, "errors": errors, "log": result.log, "elapsed_s": result.elapsed_s}
    _put_source(body, result.pull, result.src_mtime)
    body.update(src_hash=result.src_hash, head=result.head, build=result.build, pages=result.pages)
    return body


def _failed_body(errors: list[Any], log: str, elapsed_s: float) -> Body:
    """The leading keys of a failed build's body (ok false, state fail, errors, log, elapsed_s)."""
    return {"ok": False, "state": "fail", "errors": errors, "log": log, "elapsed_s": elapsed_s}


def _put_source(body: Body, pull: dict[str, Any] | None, src_mtime: float | None) -> None:
    """Append the pull record (only when a pull ran) and the compiled manuscript's mtime (only for a LaTeX build)."""
    if pull is not None:
        body["pull"] = pull
    if src_mtime is not None:
        body["src_mtime"] = src_mtime


def view_only_refused(result: ViewOnlyNoRebuild) -> NoReturn:
    """POST /api/rebuild for a view-only document: 400 view_only_no_rebuild naming the document."""
    raise HTTPError(
        400,
        "보기 전용 문서(%s)는 재빌드하지 않습니다 — PDF 파일이 바뀌면 쪽을 저절로 다시 그립니다." % result.key,
        reason="view_only_no_rebuild",
    )


def rebuild_answer(result: FinishedBuild | BuildBusy | ViewOnlyNoRebuild, full: bool) -> tuple[Body, int]:
    """POST /api/rebuild (synchronous): the finished build's body and 200, 409 {"ok": false, "busy": true} when the
    document was already building, or the view-only refusal. Without full (?log=1) the log is dropped for BuildOk and
    cut to its last LOG_TAIL_LINES lines for every other outcome (§에이전트 응답 다이어트)."""
    match result:
        case ViewOnlyNoRebuild():
            view_only_refused(result)
        case BuildBusy():
            return {"ok": False, "busy": True}, 409
        case BuildOk():
            body = finished_build_body(result)
            if not full:
                del body["log"]
            return body, 200
        case BuildOkWithErrors() | CopyFailed() | BuildFailed() | BuildAborted():
            body = finished_build_body(result)
            if not full:
                body["log"] = _last_log_lines(body["log"])
            return body, 200


def rebuild_started_answer(result: BuildStarted | BuildBusy | ViewOnlyNoRebuild) -> tuple[Body, int]:
    """POST /api/rebuild?async=1: 202 {"state": "running"} when the build started, 409 with busy true when the document
    was already building, or the view-only refusal."""
    match result:
        case ViewOnlyNoRebuild():
            view_only_refused(result)
        case BuildStarted():
            return {"state": "running"}, 202
        case BuildBusy():
            return {"state": "running", "busy": True}, 409

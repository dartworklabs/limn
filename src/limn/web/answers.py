"""The HTTP answer to every outcome of a pin operation or a build: one function per route, one `match` per function.

Each function takes the outcome value a server.py shell returned (limn.pins types, PinNotFound, the revision
services' values, limn.build's outcomes) or a request parser returned (InputRejected, limn.web.parse) and gives the body of the 200 response,
or raises HTTPError with the status and body of a refusal; the handler sends the body and its _run turns the HTTPError into the error response. Statuses, bodies and messages are the agent
contract (docs/handbook/api.md) and are kept word for word. A record goes out through `show` (server.py's public(),
which places the pin's file on this machine), and a state name comes from `state_of` (server.py's pin_state()).
Nothing here reads files, the clock or the request.
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
)
from limn.pins.edit import ClosedPinReshaped, EditRefusal, NoteTooLong, PinOutsideTree, RangeOutsideFile, StaleEdit
from limn.pins.lifecycle import (
    AgentCannotConfirm,
    AlreadyClosed,
    AlreadyDone,
    AlreadyLive,
    ClaimClosedPin,
    ClaimedByOther,
    NotClaimed,
    NotInTrash,
    PinStillOpen,
    ThreadFull,
    has_ev,
)
from limn.pins.model import DonePin, OpenPin, PinNotFound, Record, ReviewPin
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
T = TypeVar("T")

CONFIRM_BY_HUMAN = "확인은 사람이 합니다 — 테일넷 신원으로 접속해 뷰어에서 [확인]을 누르세요."
CONFIRM_OPEN_DETAIL = "열린 핀은 확인할 것이 없습니다 — 닫힌 뒤 검토 대기일 때 확인합니다."
# The log lines an agent response keeps for a non-successful build (docs/handbook/build-sync.md §에이전트 응답 다이어트).
LOG_TAIL_LINES = 40


def accepted(value: T | InputRejected) -> T:
    """A request parser's value (limn.web.parse), or the 400 of its refusal: the parser's message, word for word, and
    its reason."""
    if isinstance(value, InputRejected):
        raise HTTPError(400, value.message, reason=value.reason)
    return value


def pick_build_gone() -> Body:
    """POST /api/pick naming a page directory that is gone (limn.web.parse.PickBuildGone): a 200 whose error tells the
    viewer to pick again on the new PDF, with pdf_build_gone set."""
    return {
        "error": "화면의 PDF 가 이미 지워진 옛 빌드입니다 — 화면을 새 PDF 로 바꿨으니 다시 고르세요.",
        "reason": "pdf_build_gone",
        "pdf_build_gone": True,
    }


def restore_answer(result: OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive, show: Show) -> Body:
    """POST /api/pins/{id}/restore: the pin back in the list, or 404/409 with the old messages."""
    match result:
        case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
            return {"ok": True, "pin": show(record)}
        case NotInTrash(pid=pid):
            raise HTTPError(404, "삭제 기록에 핀 #%d 이 없습니다." % pid, reason="not_in_trash")
        case AlreadyLive(pid=pid):
            raise HTTPError(409, "핀 #%d 이 이미 있습니다." % pid, reason="pin_exists")


def claim_answer(
    result: OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound, ttl: int, eta: int | None, show: Show
) -> Body:
    """POST /api/pins/{id}/claim: the pin and the ttl/eta actually applied (clamped values), or a 409."""
    match result:
        case OpenPin(record=record):
            out: Body = {"ok": True, "pin": show(record), "ttl_min_applied": ttl}
        case PinNotFound():
            out = {"ok": False, "pin": None, "ttl_min_applied": ttl}
        case ClaimClosedPin(pin=ReviewPin(record=record) | DonePin(record=record)):
            raise HTTPError(409, "done", pin=show(record), reason="done")
        case ClaimedByOther(claimed_by=holder, claim_until=until, eta_ts=eta_ts):
            raise HTTPError(409, "claimed", claimed_by=holder, claim_until=until, eta_ts=eta_ts, reason="claimed")
    if eta is not None:
        out["eta_min_applied"] = eta  # the clamped value, if sent above the ceiling (240)
    return out


def unclaim_answer(result: OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound, show: Show) -> Body:
    """POST /api/pins/{id}/unclaim: the pin as it stands (no claim), or ok:false for an unknown id."""
    match result:
        case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
            return {"ok": True, "pin": show(record)}
        case NotClaimed(pin=OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record)):
            return {"ok": True, "pin": show(record)}
        case PinNotFound():
            return {"ok": False, "pin": None}


def reply_answer(
    result: OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound, show: Show, state_of: StateOf
) -> Body:
    """POST /api/pins/{id}/reply: the pin, its new thread entry, its state and whether the reply reopened it."""
    match result:
        case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
            msg = record["thread"][-1]
            return {
                "ok": True,
                "pin": show(record),
                "msg": msg,
                "state": state_of(record),
                "reopened": has_ev(msg, "reopen"),
            }
        case ThreadFull(limit=limit):
            raise HTTPError(
                409, "full", detail="스레드가 가득 찼습니다(답글 %d건). 새 핀으로 이어 가세요." % limit, reason="full"
            )
        case PinNotFound():
            return {"ok": False, "pin": None, "msg": None, "state": None, "reopened": False}


def state_answer(
    result: OpenPin | ReviewPin | DonePin | AlreadyClosed | PinNotFound, show: Show, state_of: StateOf
) -> Body:
    """POST /api/pins/{id}/close and /reopen: the pin as it stands now and its state, or ok:false."""
    match result:
        case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
            return {"ok": True, "pin": show(record), "state": state_of(record)}
        case AlreadyClosed(pin=ReviewPin(record=record) | DonePin(record=record)):
            return {"ok": True, "pin": show(record), "state": state_of(record)}
        case PinNotFound():
            return {"ok": False, "pin": None, "state": None}


def confirm_answer(result: DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound, show: Show) -> Body:
    """POST /api/pins/{id}/confirm for every outcome, with the statuses and bodies of the agent contract."""
    match result:
        case DonePin(record=record) | AlreadyDone(pin=DonePin(record=record)):
            return {"ok": True, "pin": show(record), "state": "done"}
        case PinNotFound():
            return {"ok": False, "pin": None, "state": None}
        case AgentCannotConfirm():
            raise HTTPError(403, CONFIRM_BY_HUMAN, reason="confirm_by_human")
        case PinStillOpen(pin=OpenPin(record=record)):
            raise HTTPError(409, "open", pin=show(record), detail=CONFIRM_OPEN_DETAIL, reason="open")


def add_answer(result: OpenPin) -> Body:
    """POST /api/pin: the new pin's id (a refused field was answered by accepted() before the pin was made)."""
    return {"id": result.record["id"]}


def edit_answer(result: OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound, show: Show) -> Body:
    """POST /api/pins/{id}/edit for every outcome, with the statuses and bodies of the agent contract."""
    match result:
        case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
            return {"ok": True, "pin": show(record)}
        case PinNotFound(pid=pid):
            raise HTTPError(404, "핀 #%d 이 없습니다." % pid, reason="pin_not_found")
        case ClosedPinReshaped(pin=ReviewPin(record=record) | DonePin(record=record)):
            raise HTTPError(409, "done", pin=show(record), detail="닫힌 핀은 메모만 고칠 수 있습니다.", reason="done")
        case StaleEdit(pin=OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record)):
            raise HTTPError(409, "conflict", pin=show(record), reason="conflict")
        case NoteTooLong(length=length, limit=limit):
            raise HTTPError(
                400, "덧붙이면 메모가 너무 깁니다(%d자, %d자 이하)." % (length, limit), reason="note_too_long"
            )
        case PinOutsideTree():
            raise HTTPError(
                400,
                "원고 디렉토리 밖을 가리키는 핀입니다 — 위치 다시 잡기(loc)로 고치세요.",
                reason="pin_outside_manuscript",
            )
        case RangeOutsideFile(lines=lines, lo=lo, hi=hi):
            raise HTTPError(
                400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (lines, lo, hi), reason="range_outside_file"
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
    The build state (BUILD_STATE, builds.json) is never changed: this applies only right before the HTTP response.
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


def rebuild_answer(result: FinishedBuild | BuildBusy, full: bool) -> tuple[Body, int]:
    """POST /api/rebuild (synchronous): the finished build's body and 200, or 409 {"ok": false, "busy": true} when the
    document was already building. Without full (?log=1) the log is dropped for BuildOk and cut to its last
    LOG_TAIL_LINES lines for every other outcome (§에이전트 응답 다이어트)."""
    match result:
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


def rebuild_started_answer(result: BuildStarted | BuildBusy) -> tuple[Body, int]:
    """POST /api/rebuild?async=1: 202 {"state": "running"} when the build started, 409 with busy true when the document
    was already building."""
    match result:
        case BuildStarted():
            return {"state": "running"}, 202
        case BuildBusy():
            return {"state": "running", "busy": True}, 409

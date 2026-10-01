"""Build status and rebuild response bodies, preserving the agent contract."""

from typing import Any, NoReturn, TypeAlias

from limn.builds.artifacts import (
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
from limn.builds.values import BuildFailureKind, FailedBuild
from limn.web.errors import HTTPError

Body: TypeAlias = dict[str, object]
# The log lines an agent response keeps for a non-successful build.
LOG_TAIL_LINES = 40


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
    """POST /api/rebuild for a document that is never rebuilt (a view-only PDF or a figure document): 400
    view_only_no_rebuild naming the document. The sentence is true of both kinds."""
    raise HTTPError(
        400,
        "재빌드하지 않는 문서(%s)입니다 — PDF 파일이 바뀌면 쪽을 저절로 다시 그립니다." % result.key,
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


BUILD_FAILURES: dict[BuildFailureKind, str] = {
    "copy": "원고 사본을 만들지 못했습니다: {detail}",
    "timeout": "시간 초과로 멈췄습니다.",
    "no_pdf": "새 PDF 가 나오지 않았습니다.",
    "no_synctex": "synctex.gz 가 없습니다 — latexmk 가 -synctex=1 을 받았는지 확인하세요.",
    "render": "쪽 이미지를 그리지 못했습니다(pdftoppm): {detail}",
    "pdf_copy": "PDF 사본을 쪽 디렉토리에 두지 못했습니다: {detail}",
    "pdf_missing": "PDF 가 없습니다: {detail}",
    "figure_unready": "그림 PDF 와 지도를 가져오지 못했습니다: {detail}",
    "crashed": "빌드 중 예상 밖 예외가 났습니다: {detail}",
    "worker_crashed": "빌드 스레드에서 예상 밖 예외가 났습니다: {detail}",
}


def build_failure_log(failure: FailedBuild) -> str:
    """The log of a failed build: its kind's text from BUILD_FAILURES with the detail filled in, then - when latexmk
    ran - a newline and latexmk's last lines. The composition root passes this to the build (limn.builds.artifacts's describe),
    which records it in the build state and history."""
    match failure:
        case CopyFailed(error=error):
            return BUILD_FAILURES["copy"].format(detail=error)
        case BuildFailed(kind=kind, detail=detail, output=output):
            text = BUILD_FAILURES[kind].format(detail=detail)
            return text if output is None else text + "\n" + output
        case BuildAborted(kind=kind, detail=detail):
            return BUILD_FAILURES[kind].format(detail=detail)

"""Revision route responses and refusals at the feature HTTP boundary."""

from typing import Any, NoReturn

from limn.revisions.core import (
    AllSlotsBusy,
    BaseAfterHead,
    BuildFailure,
    CommitNotRecent,
    DiffFailed,
    DiffUnavailable,
    DocumentBusy,
    EmptyRange,
    FailureKind,
    NoHistory,
    NoMergeBase,
    NoParent,
    NotInRepo,
    RangeRefusal,
    RevisionNotReady,
    RevisionPdfMissing,
    RevisionRefusal,
    StepFailed,
    UnsafeCache,
)
from limn.revisions.scope import PinNotInDoc, ScopeMismatch, ScopeRefusal, ScopeUnreadable, ScopeUnwritable, UnsafePath
from limn.web.errors import HTTPError


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


# A range's own refusals (issue #188, limn.revisions.core.RangeRefusal) -> (HTTP status, Korean text, API reason). A
# table beside SCOPE_REJECTIONS, read by range_http_error; the text is contract like every error text.
RANGE_REJECTIONS: dict[type[RangeRefusal], tuple[int, str, str]] = {
    BaseAfterHead: (422, "비교 기준 커밋이 대상 커밋보다 새롭습니다.", "base_after_head"),
    NoMergeBase: (422, "두 커밋에 공통 조상이 없어 비교할 수 없습니다.", "no_merge_base"),
    EmptyRange: (422, "기준과 대상이 같은 커밋이라 비교 PDF를 만들 수 없습니다.", "empty_range"),
}


def range_http_error(e: RangeRefusal) -> HTTPError:
    """The HTTP form of a range's own refusal, from RANGE_REJECTIONS."""
    code, msg, reason = RANGE_REJECTIONS[type(e)]
    return HTTPError(code, msg, reason=reason)


def revision_answer(result: dict[str, Any] | RevisionRefusal | RangeRefusal) -> dict[str, Any]:
    """A revision route's JSON body (the history, the source diff, or a comparison build's status), or its refusal's
    answer: a range's own through RANGE_REJECTIONS, every other through revision_refused."""
    if isinstance(result, dict):
        return result
    if isinstance(result, BaseAfterHead | NoMergeBase | EmptyRange):
        raise range_http_error(result)
    revision_refused(result)


def revision_start_answer(result: dict[str, Any] | RevisionRefusal | RangeRefusal) -> tuple[dict[str, Any], int]:
    """POST /api/revision-build: the comparison build's status with 202 while it is running (just started or already
    under way), 200 once it has an answer (ready or failed); a refusal through revision_refused."""
    body = revision_answer(result)
    return body, 202 if body["state"] == "running" else 200


def revision_pdf_answer(result: bytes | RevisionRefusal | RangeRefusal) -> bytes:
    """GET /api/revision-pdf: the comparison PDF's bytes, or its refusal's answer (a range's own through
    RANGE_REJECTIONS)."""
    if isinstance(result, bytes):
        return result
    if isinstance(result, BaseAfterHead | NoMergeBase | EmptyRange):
        raise range_http_error(result)
    revision_refused(result)


# A failed step of a comparison build (limn.revisions.core.StepFailed.kind) -> (message, API reason) its "error" status
# carries (api.md §변경 보기와 비교 PDF). These never become an HTTP status of their own: the build runs in the
# background and GET /api/revision-build reports the stored status. tests check that every kind has its row.
REVISION_FAILURES: dict[FailureKind, tuple[str, str]] = {
    "tool_start": ("비교 PDF 실행 도구를 시작하지 못했습니다.", "tool_unavailable"),
    "timeout": ("비교 PDF 실행 시간이 초과됐습니다.", "timeout"),
    "size": ("비교 입력 또는 실행 로그가 크기 제한을 넘었습니다.", "size_limit"),
    "snapshot_read": ("Git 원고 사본을 읽지 못했습니다.", "snapshot_failed"),
    "unsafe_snapshot": ("사본에 허용되지 않는 경로·심링크·하위 저장소가 있습니다.", "unsafe_snapshot"),
    "snapshot_size": ("원고 사본이 파일 수·크기 제한을 넘었습니다.", "size_limit"),
    "snapshot_timeout": ("Git 사본 생성 시간이 초과됐습니다.", "timeout"),
    "snapshot_blob": ("Git 원고 파일을 읽지 못했습니다.", "snapshot_failed"),
    "missing_main": ("해당 커밋에 현재 메인 원고 경로가 없습니다. 소스 변경사항을 확인하세요.", "missing_main"),
    "sandbox_tools": ("비교 PDF에는 bwrap, latexdiff, latexmk가 필요합니다.", "tool_unavailable"),
    "sandbox_system": ("비교 PDF 도구는 /usr 아래의 시스템 설치를 사용해야 합니다.", "tool_unavailable"),
    "diff_failed": (
        "latexdiff가 원고를 비교하지 못했습니다. 누락된 포함 파일 또는 실행 격리 설정을 확인하세요.",
        "diff_failed",
    ),
    "compile_failed": (
        "비교 PDF 컴파일에 실패했습니다. 이 뷰어는 pdfLaTeX를 사용합니다. 소스 변경사항을 확인하세요.",
        "compile_failed",
    ),
    "invalid_pdf": ("비교 PDF 결과가 올바르지 않습니다.", "invalid_pdf"),
}


def revision_failure_text(failure: BuildFailure) -> tuple[str, str]:
    """(message, API reason) a failed comparison build records: a step's from REVISION_FAILURES, a pin-scoping
    refusal's from SCOPE_REJECTIONS (the same text its HTTP answer has)."""
    if isinstance(failure, StepFailed):
        return REVISION_FAILURES[failure.kind]
    _, msg, reason = SCOPE_REJECTIONS[type(failure)]
    return msg, reason


SCOPE_REJECTIONS: dict[type[ScopeRefusal], tuple[int, str, str]] = {
    PinNotInDoc: (404, "이 문서의 핀이 아닙니다.", "pin_not_in_doc"),
    ScopeUnreadable: (422, "이 핀의 변경만 골라 적용하지 못했습니다.", "scope_failed"),
    ScopeMismatch: (422, "이 핀의 변경을 커밋에서 다시 찾지 못했습니다.", "scope_failed"),
    UnsafePath: (422, "사본에 허용되지 않는 경로가 있습니다.", "unsafe_snapshot"),
    ScopeUnwritable: (422, "이 핀의 변경만 넣은 사본을 쓰지 못했습니다.", "scope_failed"),
}


def scope_http_error(e: ScopeRefusal) -> HTTPError:
    """The HTTP form of a pin-scoping refusal, from SCOPE_REJECTIONS."""
    code, msg, reason = SCOPE_REJECTIONS[type(e)]
    return HTTPError(code, msg, reason=reason)

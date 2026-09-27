"""Revision route responses and refusals at the feature HTTP boundary."""

from typing import Any, NoReturn

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
from limn.web.errors import HTTPError, scope_http_error


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

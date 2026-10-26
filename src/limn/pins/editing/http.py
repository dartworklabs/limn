"""HTTP entry points and responses for pin creation and editing."""

from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from typing import Any, NoReturn, TypeAlias

from limn.pins.editing import input as editing_input
from limn.pins.editing.rules import (
    AddRefusal,
    ClosedPinReshaped,
    EditBaseChanged,
    EditRefusal,
    NoteTooLong,
    PinOutsideTree,
    RangeOutsideFile,
    StaleEdit,
    SuggestBaseChanged,
    SuggestNoop,
    SuggestRangeTooLong,
    SuggestRefusal,
    SuggestTextTooLong,
    SuggestUnsupported,
    VerdictByAgent,
    VerdictConflict,
    VerdictFixed,
    VerdictPageTarget,
    VerdictRefusal,
    VerdictUnknown,
    VerdictUnsupported,
)
from limn.pins.editing.service import EditTarget, PinEditing
from limn.pins.model import DonePin, OpenPin, PinNotFound, Record, ReviewPin
from limn.runtime.documents import Doc
from limn.security.access import PostAuthority
from limn.web.answers import accepted
from limn.web.errors import HTTPError
from limn.web.parse import DocumentFacts

Body: TypeAlias = dict[str, object]

# The 409 a suggested edit gets when the lines it would replace no longer read as its base: the body adds `current`,
# what they read now, so the author can rewrite against it (and an edit's 409 the latest `pin`, like a stale edit's).
SUGGEST_BASE_CHANGED = (
    "제안 수정의 base 가 지금 원문과 다릅니다 — 그사이 그 줄들이 바뀌었습니다. current 의 지금 글을 보고 다시 쓰세요."
)
# The refusals of a new pin's verdict (docs/superpowers/specs/2026-10-26-verdict-pins.md §HTTP API): agent contract
# strings, never reworded.
VERDICT_HUMAN = "판정은 사람이 정합니다 — 에이전트는 판정 핀을 만들지 않습니다."
VERDICT_UNSUPPORTED = "이 문서에는 판정 낱말이 없습니다."
VERDICT_UNKNOWN = "이 문서의 판정 낱말이 아닙니다."
VERDICT_CONFLICT = "판정 핀은 질문·제안 수정과 함께 쓰지 않습니다."
VERDICT_FIXED = "판정 핀은 판정과 대상을 바꾸지 않습니다 — 새 판정 핀을 찍거나 이 핀을 지웁니다."
VERDICT_PAGE_TARGET = "그 쪽의 그림을 확인하지 못했습니다 — 그림 위를 끌어 고른 뒤 판정합니다."


@dataclass(frozen=True)
class EditingRequests:
    """The run-specific collaborators used by pin create and edit requests."""

    pin_editing: PinEditing
    known_people: Callable[[], Collection[str]]
    document_facts: Callable[[Doc], DocumentFacts]
    edit_scope: Callable[[int], EditTarget]
    public: Callable[[Record], dict[str, Any]]

    def assignee_people(self, body: dict[str, Any]) -> Collection[str]:
        """Read known assignees only when the body names one."""
        return self.known_people() if body.get("assignee") is not None else ()


def add(app: EditingRequests, document: Doc, actor: PostAuthority, body: dict[str, Any]) -> Body:
    """Parse and create one pin after shared guards and document selection."""
    request = accepted(editing_input.parse_add(body, app.assignee_people(body), app.document_facts(document)))
    return add_answer(app.pin_editing.add_pin(document, request, actor))


def edit(app: EditingRequests, pid: int, actor: PostAuthority, body: dict[str, Any]) -> Body:
    """Check edit fields before loading the pin's document, then validate its location against that document - or,
    for a verdict pin, leave it unread for the editing rules to refuse (verdict_fixed)."""
    parsed = accepted(editing_input.parse_edit(body, app.assignee_people(body)))
    target = app.edit_scope(pid)
    facts = app.document_facts(target.document)
    place = accepted(editing_input.parse_edit_place(parsed, target.region, facts, verdict=target.verdict))
    request = replace(parsed.request, place=place)
    result = app.pin_editing.edit_pin(pid, request, actor, target.region, target.document.builds_from_source)
    return edit_answer(result, app.public)


def add_answer(result: OpenPin | AddRefusal) -> Body:
    """POST /api/pin: the new pin's id, or the refusal of its suggested edit - 400 for the suggestion's own rules
    (suggest_refused), 409 suggest_base_changed with `current` when its lines no longer read as its base - or of its
    verdict (verdict_refused)."""
    match result:
        case OpenPin(core=core):
            return {"id": core.id}
        case SuggestBaseChanged(current=current):
            raise HTTPError(409, SUGGEST_BASE_CHANGED, reason="suggest_base_changed", current=current)
        case SuggestUnsupported() | SuggestRangeTooLong() | SuggestTextTooLong() | SuggestNoop():
            suggest_refused(result)
        case VerdictByAgent() | VerdictUnsupported() | VerdictUnknown() | VerdictConflict() | VerdictPageTarget():
            verdict_refused(result)


def verdict_refused(result: VerdictRefusal) -> NoReturn:
    """The refusal of a new pin's verdict: 403 verdict_human for an agent, 400 verdict_unsupported for a document
    without usable words, 400 verdict_unknown with the document's keys as `choices`, 400 verdict_conflict for a
    question or a suggested edit, 400 verdict_page_target for a whole figure its build's map does not confirm."""
    match result:
        case VerdictByAgent():
            raise HTTPError(403, VERDICT_HUMAN, reason="verdict_human")
        case VerdictUnsupported():
            raise HTTPError(400, VERDICT_UNSUPPORTED, reason="verdict_unsupported")
        case VerdictUnknown(choices=choices):
            raise HTTPError(400, VERDICT_UNKNOWN, reason="verdict_unknown", choices=list(choices))
        case VerdictConflict():
            raise HTTPError(400, VERDICT_CONFLICT, reason="verdict_conflict")
        case VerdictPageTarget():
            raise HTTPError(400, VERDICT_PAGE_TARGET, reason="verdict_page_target")


def suggest_refused(result: SuggestRefusal) -> NoReturn:
    """The 400 of a suggestion's own rule (limn.pins.editing.rules.check_suggestion), the same for a new pin and an
    edit: suggest_unsupported, suggest_too_long (the range or a text, with its count and limit) or suggest_noop."""
    match result:
        case SuggestUnsupported():
            raise HTTPError(
                400,
                "제안 수정은 LaTeX 문서의 줄 핀에만 둘 수 있습니다 — 보기 전용 PDF·그림 문서의 핀과 영역 핀은 메모로 요청하세요.",
                reason="suggest_unsupported",
            )
        case SuggestRangeTooLong(lines=lines, limit=limit):
            raise HTTPError(
                400,
                "제안 수정은 %d줄 이하의 범위에만 둘 수 있습니다(이 범위는 %d줄)." % (limit, lines),
                reason="suggest_too_long",
            )
        case SuggestTextTooLong(field=field, length=length, limit=limit):
            raise HTTPError(
                400, "suggest.%s 가 너무 깁니다(%d자, %d자 이하)." % (field, length, limit), reason="suggest_too_long"
            )
        case SuggestNoop():
            raise HTTPError(400, "suggest.text 가 base 와 같습니다 — 바꿀 글이 없습니다.", reason="suggest_noop")


def edit_answer(
    result: OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound, show: Callable[[Record], object]
) -> Body:
    """POST /api/pins/{id}/edit for every outcome, preserving the contract's statuses and bodies."""
    match result:
        case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
            return {"ok": True, "pin": show(record)}
        case PinNotFound(pid=pid):
            raise HTTPError(404, "핀 #%d 이 없습니다." % pid, reason="pin_not_found")
        case VerdictFixed():
            raise HTTPError(400, VERDICT_FIXED, reason="verdict_fixed")
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
        case SuggestUnsupported() | SuggestRangeTooLong() | SuggestTextTooLong() | SuggestNoop():
            suggest_refused(result)
        case EditBaseChanged(
            pin=OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record), current=current
        ):
            raise HTTPError(409, SUGGEST_BASE_CHANGED, reason="suggest_base_changed", current=current, pin=show(record))

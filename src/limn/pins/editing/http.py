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
)
from limn.pins.editing.service import PinEditing
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


@dataclass(frozen=True)
class EditingRequests:
    """The run-specific collaborators used by pin create and edit requests."""

    pin_editing: PinEditing
    known_people: Callable[[], Collection[str]]
    document_facts: Callable[[Doc], DocumentFacts]
    edit_scope: Callable[[int], tuple[bool, Doc]]
    public: Callable[[Record], dict[str, Any]]

    def assignee_people(self, body: dict[str, Any]) -> Collection[str]:
        """Read known assignees only when the body names one."""
        return self.known_people() if body.get("assignee") is not None else ()


def add(app: EditingRequests, document: Doc, actor: PostAuthority, body: dict[str, Any]) -> Body:
    """Parse and create one pin after shared guards and document selection."""
    request = accepted(editing_input.parse_add(body, app.assignee_people(body), app.document_facts(document)))
    return add_answer(app.pin_editing.add_pin(document, request, actor))


def edit(app: EditingRequests, pid: int, actor: PostAuthority, body: dict[str, Any]) -> Body:
    """Check edit fields before loading the pin's document, then validate its location."""
    parsed = accepted(editing_input.parse_edit(body, app.assignee_people(body)))
    region, document = app.edit_scope(pid)
    place = accepted(editing_input.parse_edit_place(parsed, region, app.document_facts(document)))
    request = replace(parsed.request, place=place)
    return edit_answer(app.pin_editing.edit_pin(pid, request, actor, region, document.builds_from_source), app.public)


def add_answer(result: OpenPin | AddRefusal) -> Body:
    """POST /api/pin: the new pin's id, or the refusal of its suggested edit - 400 for the suggestion's own rules
    (suggest_refused), 409 suggest_base_changed with `current` when its lines no longer read as its base."""
    match result:
        case OpenPin(core=core):
            return {"id": core.id}
        case SuggestBaseChanged(current=current):
            raise HTTPError(409, SUGGEST_BASE_CHANGED, reason="suggest_base_changed", current=current)
        case SuggestUnsupported() | SuggestRangeTooLong() | SuggestTextTooLong() | SuggestNoop():
            suggest_refused(result)


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

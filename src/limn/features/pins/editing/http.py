"""HTTP entry points and responses for pin creation and editing."""

from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from typing import Any, TypeAlias

from limn.access import PostAuthority
from limn.documents import Doc
from limn.features.pins.editing import input as editing_input
from limn.features.pins.editing.rules import (
    ClosedPinReshaped,
    EditRefusal,
    NoteTooLong,
    PinOutsideTree,
    RangeOutsideFile,
    StaleEdit,
)
from limn.features.pins.editing.service import PinEditing
from limn.pins.model import DonePin, OpenPin, PinNotFound, Record, ReviewPin
from limn.web.answers import accepted
from limn.web.errors import HTTPError
from limn.web.parse import DocumentFacts

Body: TypeAlias = dict[str, object]


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
    return edit_answer(app.pin_editing.edit_pin(pid, replace(parsed.request, place=place), actor, region), app.public)


def add_answer(result: OpenPin) -> Body:
    """POST /api/pin: the new pin's id."""
    return {"id": result.core.id}


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

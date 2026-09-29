"""HTTP inputs and answers for pin close, reopen, and confirm."""

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol, TypeAlias

from limn.config import RunConfig
from limn.features.pins.lifecycle import input as lifecycle_input
from limn.features.pins.lifecycle.rules import (
    AgentCannotConfirm,
    AlreadyClosed,
    AlreadyDone,
    PinStillOpen,
    ThreadFull,
    last_entry,
)
from limn.features.pins.lifecycle.service import PinLifecycle
from limn.pins.model import DonePin, OpenPin, PinNotFound, Record, ReviewPin
from limn.web.answers import CONFIRM_BY_HUMAN, accepted
from limn.web.errors import HTTPError

Body: TypeAlias = dict[str, object]
Show: TypeAlias = Callable[[Record], object]
StateOf: TypeAlias = Callable[[Record], str]

CONFIRM_OPEN_DETAIL = "열린 핀은 확인할 것이 없습니다 — 닫힌 뒤 검토 대기일 때 확인합니다."


class LifecycleApp(Protocol):
    """Only the run-specific collaborators these lifecycle routes use."""

    C: RunConfig
    pin_lifecycle: PinLifecycle

    def public(self, record: Record) -> dict[str, Any]:
        """Render one stored pin for this application's HTTP response."""
        ...

    def pin_state(self, record: Record) -> str:
        """Return the public state name of one pin."""
        ...


def reply(
    app: LifecycleApp,
    pid: int,
    actor: dict[str, Any],
    body: dict[str, Any],
    is_human: Callable[[], bool],
) -> Body:
    """Parse, decide, and answer POST /api/pins/{id}/reply after shared guards."""
    request = accepted(lifecycle_input.parse_reply(body))
    human = is_human()
    return reply_answer(
        app.pin_lifecycle.reply_pin(pid, request.text, actor, request.hints, reopen=request.reopen, human=human),
        app.public,
        app.pin_state,
    )


def close(
    app: LifecycleApp,
    pid: int,
    actor: dict[str, Any],
    body: dict[str, Any],
    review_on_close: Callable[[bool | None], bool | None],
) -> Body:
    """Parse, decide, and answer POST /api/pins/{id}/close after shared guards."""
    request = accepted(lifecycle_input.parse_close(body, app.C.src, app.C.state))
    review = review_on_close(request.review)
    return state_answer(
        app.pin_lifecycle.close_pin(pid, actor, replace(request, review=review)), app.public, app.pin_state
    )


def reopen(app: LifecycleApp, pid: int, actor: dict[str, Any], body: dict[str, Any]) -> Body:
    """Parse, decide, and answer POST /api/pins/{id}/reopen after shared guards."""
    reason, hints = accepted(lifecycle_input.parse_reopen(body))
    return state_answer(app.pin_lifecycle.reopen_pin(pid, actor, reason, hints), app.public, app.pin_state)


def confirm(app: LifecycleApp, pid: int, actor: dict[str, Any]) -> Body:
    """Decide and answer POST /api/pins/{id}/confirm after shared guards."""
    return confirm_answer(app.pin_lifecycle.confirm_pin(pid, actor), app.public)


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


def reply_answer(
    result: OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound, show: Show, state_of: StateOf
) -> Body:
    """POST /api/pins/{id}/reply: the pin, its new thread entry, its state and whether the reply reopened it."""
    match result:
        case OpenPin() | ReviewPin() | DonePin():
            record, entry = result.record, last_entry(result)
            return {
                "ok": True,
                "pin": show(record),
                "msg": entry.record,
                "state": state_of(record),
                "reopened": entry.ev == "reopen",
            }
        case ThreadFull(limit=limit):
            raise HTTPError(
                409, "full", detail="스레드가 가득 찼습니다(답글 %d건). 새 핀으로 이어 가세요." % limit, reason="full"
            )
        case PinNotFound():
            return {"ok": False, "pin": None, "msg": None, "state": None, "reopened": False}

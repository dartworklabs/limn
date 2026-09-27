"""Pin close, reopen, and confirm transactions owned by the lifecycle feature."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from limn.mentions import resolve_mentions
from limn.pins.lifecycle import (
    AgentCannotConfirm,
    AlreadyClosed,
    AlreadyDone,
    CloseRequest,
    PinStillOpen,
    confirm,
    confirmer,
    decide_close,
    decide_reopen,
    evolve_close,
    reopen_request,
)
from limn.pins.model import DonePin, OpenPin, Pin, PinNotFound, ReviewPin
from limn.service.context import Event, PinContext, Row, load_pin, typed_actor


@dataclass(frozen=True)
class PinLifecycle:
    """The three pin transitions bound to one application's context factory."""

    context: Callable[[], PinContext]

    def close_pin(
        self, pid: int, actor: Mapping[str, Any], request: CloseRequest
    ) -> ReviewPin | DonePin | AlreadyClosed | PinNotFound:
        """Close pin pid under the pin lock, then tell the author when it now awaits review (docs/handbook/api.md §닫을 때 사유 남기기).

        Re-closing a closed pin changes nothing (AlreadyClosed) - a second close must not overwrite done_at/closed_by
        and erase who closed it first (observed defect). An agent's close awaits review unless the request says:
        out of 42 observed cases an author reopened an agent-closed pin twice with no record that a person had looked.
        A person with the agent role closes into review because the handler sets request.review for them.
        """
        ctx = self.context()
        evs: list[Event | None] = []

        def fn(pins: list[Pin]) -> tuple[ReviewPin | DonePin | AlreadyClosed | PinNotFound, bool]:
            """The transact() step: decide the close on pin pid and, if it was open, write it and queue review_requested."""
            found = load_pin(pins, pid)
            if isinstance(found, PinNotFound):
                return found, False
            i, pin = found
            event = decide_close(pin, typed_actor(actor), ctx.now(), request)
            if isinstance(event, AlreadyClosed):
                return event, False
            if not isinstance(pin, OpenPin):
                raise AssertionError("decide_close accepted a pin that was already closed")
            closed = evolve_close(pin, event)
            pins[i] = closed
            r = closed.record
            if isinstance(closed, ReviewPin):
                evs.append(
                    ctx.make_event(
                        "review_requested", r, actor, [(r.get("author") or {}).get("login")], msg=r["thread"][-1]
                    )
                )
            return closed, True

        with ctx.store.lock:
            out = ctx.store.transact(fn)[1]
            ctx.emit_events(evs)
        return out

    def reopen_pin(
        self, pid: int, actor: Mapping[str, Any], reason: str | None = None, hints: Iterable[str] | None = None
    ) -> OpenPin | PinNotFound:
        """Reopen pin pid under the pin lock; a closed pin records the reason and notifies (see _reopen). rev goes up
        even for a pin that was already open."""
        ctx = self.context()
        evs: list[Event | None] = []

        def fn(pins: list[Pin]) -> tuple[OpenPin | PinNotFound, bool]:
            """The transact() step: reopen pin pid in place (always a write) and queue its notices."""
            found = load_pin(pins, pid)
            if isinstance(found, PinNotFound):
                return found, False
            i, pin = found
            opened = _reopen(ctx, pin, pins, actor, reason, hints, evs)
            pins[i] = opened
            return opened, True

        with ctx.store.lock:
            out = ctx.store.transact(fn)[1]
            ctx.emit_events(evs)
        return out

    def confirm_pin(
        self, pid: int, actor: Mapping[str, Any]
    ) -> DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound:
        """Awaiting review -> done, by a person only (docs/handbook/api.md §검토 대기).

        An agent is refused before the store is touched. Otherwise the pin is loaded under the pin lock
        (transact) and lifecycle.confirm() decides; only a new DonePin is written, in the pin's place, so the saved line
        keeps its field order. Every other outcome is returned unchanged for the HTTP layer to answer. No notice.
        """
        by = confirmer(typed_actor(actor))
        if isinstance(by, AgentCannotConfirm):
            return by
        person = by
        ctx = self.context()

        def fn(pins: list[Pin]) -> tuple[DonePin | AlreadyDone | PinStillOpen | PinNotFound, bool]:
            """The transact() step: confirm pin pid; written only when it becomes done."""
            found = load_pin(pins, pid)
            if isinstance(found, PinNotFound):
                return found, False
            i, pin = found
            result = confirm(pin, person, ctx.now())
            if isinstance(result, DonePin):
                pins[i] = result
                return result, True
            return result, False

        return ctx.store.transact(fn)[1]


def _reopen(
    ctx: PinContext,
    pin: Pin,
    pins: list[Pin],
    actor: Mapping[str, Any],
    reason: str | None,
    hints: Iterable[str] | None,
    evs: list[Event | None],
) -> OpenPin:
    """POST /reopen's step (inside transact): the pin reopened by limn.pins.lifecycle.reopen_request, rev bumped, and
    - if it was closed - a mention queued for everyone the reason @-tags and reopened for the author (the @-tags are
    resolved against the people on pins). A reopening reply calls reopen_request itself in reply_pin. Returns the
    reopened pin; the caller puts it in pin's place."""
    ment = (
        resolve_mentions(reason or "", ctx.known_people(pins), hints, exclude=(actor or {}).get("login"))
        if not isinstance(pin, OpenPin)
        else []
    )
    event = decide_reopen(pin, typed_actor(actor), ctx.now(), reason, tuple(ment))
    opened = reopen_request(pin, event)
    if event.was_closed:
        r = opened.record
        _reopen_notices(ctx, r, actor, ment, r["thread"][-1], evs)
    return opened


def _reopen_notices(
    ctx: PinContext, r: Row, actor: Mapping[str, Any], ment: list[str], msg: Mapping[str, Any], evs: list[Event | None]
) -> None:
    """Queue the notices of a reopen: a mention for everyone the reason @-tags, reopened for the author otherwise."""
    evs.append(ctx.make_event("mention", r, actor, ment, msg=msg))  # same rule as a reply: every @-tag here
    evs.append(
        ctx.make_event(
            "reopened", r, actor, [lg for lg in [(r.get("author") or {}).get("login")] if lg not in ment], msg=msg
        )
    )

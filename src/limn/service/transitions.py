"""Replying to, closing, reopening and confirming a pin (docs/handbook/api.md §스레드, §닫기, §검토 대기).

Each shell loads the pin under the pin lock (PinStore.transact), asks limn.pins.lifecycle what happens, rewrites the
record in place only when the rule accepts (so the saved line keeps its field order) and emits the notices after the
write committed. Every outcome goes back unchanged for the HTTP layer to answer.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from limn.mentions import pin_mentions_all, resolve_mentions
from limn.pins.lifecycle import (
    AgentCannotConfirm,
    AlreadyClosed,
    AlreadyDone,
    CloseRequest,
    PinReopened,
    PinStillOpen,
    Replied,
    ThreadFull,
    confirm,
    confirmer,
    decide_close,
    decide_reopen,
    decide_reply,
    evolve_close,
    evolve_reopen,
    evolve_reply,
    reopen_request,
    reopens_on_reply,
)
from limn.pins.model import DonePin, OpenPin, Pin, PinNotFound, Record, ReviewPin, parse_pin
from limn.service.context import Event, PinContext, Row, is_agent, typed_actor
from limn.store import find_pin


class CloseChange(Protocol):
    """One changed range a close records, as limn.web.parse.parse_close_changes gives it."""

    def record(self) -> Record:
        """Its stored form in the pin's `changes`."""
        ...


def reply_pin(ctx: PinContext, pid: int, text: str, actor: Mapping[str, Any], hints: Iterable[str] | None = None,
              reopen: bool | None = None,
              human: bool | None = None) -> OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound:
    """One reply (from a person or an agent); the pin as it stands after it is returned, its new entry last in the thread.

    Whether it also reopens the pin is decided by limn.pins.lifecycle.reopens_on_reply() - the viewer only previews it.
    `human` is whether the poster is a person (the handler also counts a person with the agent role as an agent); None
    means "not an agent actor". A reopening reply is recorded exactly like POST /reopen with the reply as its reason
    (ev=reopen, the same notices), so the pin returns to the open table of pins.md with that reason. Otherwise it is a
    plain reply, refused as ThreadFull when the thread already holds ctx.thread_max replies; every @-tag in it is a
    mention (whether or not tagged before), and the author plus everyone previously tagged on this pin who is not
    tagged here gets a replied notice. The poster themself gets neither.
    """
    evs: list[Event | None] = []
    human = (not is_agent(actor)) if human is None else human

    def fn(rows: list[Row]) -> tuple[OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound, bool]:
        """The transact() step: decide the reply on pin pid and, unless the thread is full, write it and queue its notices."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        ment = resolve_mentions(text, ctx.known_people(rows), hints, exclude=(actor or {}).get("login"))
        # tagging an agent-role account is not asking a person
        persons = [lg for lg in ment if ctx.role_of(lg) != "agent"]
        pin = parse_pin(r)
        event = decide_reply(pin, typed_actor(actor), ctx.now(), text, tuple(ment),
                             reopens_on_reply(pin, human, persons, reopen), ctx.thread_max)
        author = (r.get("author") or {}).get("login")
        before = pin_mentions_all(r)
        replied: OpenPin | ReviewPin | DonePin
        match event:
            case ThreadFull():
                return event, False
            case PinReopened():
                replied = reopen_request(pin, event)
                r.clear()
                r.update(replied.record)
                msg = r["thread"][-1]
                _reopen_notices(ctx, r, actor, ment, msg, evs)
                # Everyone else tagged on the pin earlier would have heard of a plain reply (replied) - reopening must
                # not silence them.
                evs.append(ctx.make_event("replied", r, actor,
                                          [lg for lg in sorted(before) if lg != author and lg not in ment], msg=msg))
            case Replied():
                replied = _with_reply(pin, event)
                r.clear()
                r.update(replied.record)
                msg = r["thread"][-1]
                # Every @-tag in this reply is a mention, even for someone tagged earlier on the pin (observed in the
                # v0.2.0 QA: a second "@Bob ..." reached nobody). Everyone else involved gets replied - never both.
                evs.append(ctx.make_event("mention", r, actor, ment, msg=msg))
                evs.append(ctx.make_event("replied", r, actor, [lg for lg in [author] + sorted(before) if lg not in ment],
                                          msg=msg))
        return replied, True
    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def _with_reply(pin: Pin, event: Replied) -> Pin:
    """evolve_reply() on a pin of any state: the rule keeps the state, so each state goes in as its own type."""
    match pin:
        case OpenPin():
            return evolve_reply(pin, event)
        case ReviewPin():
            return evolve_reply(pin, event)
        case DonePin():
            return evolve_reply(pin, event)


def set_done(ctx: PinContext, pid: int, done: bool, actor: Mapping[str, Any], reply: str | None = None,
             ref: str | None = None, review: bool | None = None, reason: str | None = None,
             hints: Iterable[str] | None = None, changes: Sequence[CloseChange] | None = None,
             ) -> OpenPin | ReviewPin | DonePin | AlreadyClosed | PinNotFound:
    """Close (done=True) or reopen (done=False) - the single entry POST /close and /reopen and older callers use.

    `reply`/`ref`/`changes` (already parsed by limn.web.parse.parse_close_body/parse_close_changes: changes is a
    sequence of CloseChange, each giving its stored form by .record()) and `review` belong to a close; `reason` and
    `hints` to a reopen. The rules are in limn.pins.lifecycle; see close_pin and reopen_pin.
    """
    if done:
        return close_pin(ctx, pid, actor, CloseRequest(reply, ref, tuple(c.record() for c in changes or ()), review))
    return reopen_pin(ctx, pid, actor, reason, hints)


def close_pin(ctx: PinContext, pid: int, actor: Mapping[str, Any],
              request: CloseRequest) -> ReviewPin | DonePin | AlreadyClosed | PinNotFound:
    """Close pin pid under the pin lock, then tell the author when it now awaits review (docs/handbook/api.md §닫기).

    Re-closing a closed pin changes nothing (AlreadyClosed) - a second close must not overwrite done_at/closed_by
    and erase who closed it first (observed defect). An agent's close awaits review unless the request says:
    out of 42 observed cases an author reopened an agent-closed pin twice with no record that a person had looked.
    A person with the agent role closes into review because the handler sets request.review for them.
    """
    evs: list[Event | None] = []

    def fn(rows: list[Row]) -> tuple[ReviewPin | DonePin | AlreadyClosed | PinNotFound, bool]:
        """The transact() step: decide the close on pin pid and, if it was open, write it and queue review_requested."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        pin = parse_pin(r)
        event = decide_close(pin, typed_actor(actor), ctx.now(), request)
        if isinstance(event, AlreadyClosed):
            return event, False
        closed = evolve_close(pin, event)
        r.clear()
        r.update(closed.record)
        if isinstance(closed, ReviewPin):
            evs.append(ctx.make_event("review_requested", r, actor, [(r.get("author") or {}).get("login")],
                                      msg=r["thread"][-1]))
        return closed, True
    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def reopen_pin(ctx: PinContext, pid: int, actor: Mapping[str, Any], reason: str | None,
               hints: Iterable[str] | None) -> OpenPin | PinNotFound:
    """Reopen pin pid under the pin lock; a closed pin records the reason and notifies (see _reopen). rev goes up
    even for a pin that was already open, as before."""
    evs: list[Event | None] = []

    def fn(rows: list[Row]) -> tuple[OpenPin | PinNotFound, bool]:
        """The transact() step: reopen pin pid in place (always a write) and queue its notices."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        opened = _reopen(ctx, r, rows, actor, reason, hints, evs, request=True)
        return opened, True
    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def _reopen(ctx: PinContext, r: Row, rows: list[Row], actor: Mapping[str, Any], reason: str | None,
            hints: Iterable[str] | None, evs: list[Event | None], request: bool = False) -> OpenPin:
    """Reopens r in place (inside transact) by limn.pins.lifecycle's rule, and - if the pin was closed - queues a
    mention for everyone the reason @-tags and reopened for the author. Used by POST /reopen (request=True, which
    also bumps rev); a reopening reply goes through reopen_request itself in reply_pin. Returns the reopened pin."""
    pin = parse_pin(r)
    ment = resolve_mentions(reason or "", ctx.known_people(rows), hints, exclude=(actor or {}).get("login")) \
        if not isinstance(pin, OpenPin) else []
    event = decide_reopen(pin, typed_actor(actor), ctx.now(), reason, tuple(ment))
    opened = reopen_request(pin, event) if request else evolve_reopen(pin, event)
    r.clear()
    r.update(opened.record)
    if event.was_closed:
        _reopen_notices(ctx, r, actor, ment, r["thread"][-1], evs)
    return opened


def _reopen_notices(ctx: PinContext, r: Row, actor: Mapping[str, Any], ment: list[str], msg: Mapping[str, Any],
                    evs: list[Event | None]) -> None:
    """Queue the notices of a reopen: a mention for everyone the reason @-tags, reopened for the author otherwise."""
    evs.append(ctx.make_event("mention", r, actor, ment, msg=msg))    # same rule as a reply: every @-tag here
    evs.append(ctx.make_event("reopened", r, actor, [lg for lg in [(r.get("author") or {}).get("login")]
                                                     if lg not in ment], msg=msg))


def confirm_pin(ctx: PinContext, pid: int,
                actor: Mapping[str, Any]) -> DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound:
    """Awaiting review -> done, by a person only (docs/handbook/api.md §검토 대기).

    An agent is refused before the store is touched, as before. Otherwise the pin is loaded under the pin lock
    (transact) and lifecycle.confirm() decides; only a new DonePin is written, in place, so the saved line
    keeps its field order. Every other outcome is returned unchanged for the HTTP layer to answer. No notice.
    """
    by = confirmer(typed_actor(actor))
    if isinstance(by, AgentCannotConfirm):
        return by
    person = by

    def fn(rows: list[Row]) -> tuple[DonePin | AlreadyDone | PinStillOpen | PinNotFound, bool]:
        """The transact() step: confirm pin pid; written only when it becomes done."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        result = confirm(parse_pin(r), person, ctx.now())
        if isinstance(result, DonePin):
            r.clear()
            r.update(result.record)
            return result, True
        return result, False
    return ctx.store.transact(fn)[1]

"""Reply to a pin, including a reply that reopens it (docs/handbook/api.md §스레드 (답글)).

The reply shell loads the pin under the pin lock (PinStore.transact), asks limn.pins.lifecycle what happens, puts the pin's
next state in its place only when the rule accepts (its record keeps the stored field order, so the saved line changes
only where the transition changed it) and emits the notices after the write committed. Every outcome goes back unchanged for the HTTP layer to answer.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from limn.features.pins.lifecycle.service import _reopen_notices
from limn.mentions import pin_mentions_all, resolve_mentions
from limn.pins.lifecycle import (
    PinReopened,
    Replied,
    ThreadFull,
    decide_reply,
    evolve_reply,
    reopen_request,
    reopens_on_reply,
)
from limn.pins.model import DonePin, OpenPin, Pin, PinNotFound, ReviewPin
from limn.service.context import Event, PinContext, is_agent, load_pin, typed_actor


def reply_pin(
    ctx: PinContext,
    pid: int,
    text: str,
    actor: Mapping[str, Any],
    hints: Iterable[str] | None = None,
    reopen: bool | None = None,
    human: bool | None = None,
) -> OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound:
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

    def fn(pins: list[Pin]) -> tuple[OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound, bool]:
        """The transact() step: decide the reply on pin pid and, unless the thread is full, write it and queue its notices."""
        found = load_pin(pins, pid)
        if isinstance(found, PinNotFound):
            return found, False
        i, pin = found
        ment = resolve_mentions(text, ctx.known_people(pins), hints, exclude=(actor or {}).get("login"))
        # tagging an agent-role account is not asking a person
        persons = [lg for lg in ment if ctx.role_of(lg) != "agent"]
        event = decide_reply(
            pin,
            typed_actor(actor),
            ctx.now(),
            text,
            tuple(ment),
            reopens_on_reply(pin, human, persons, reopen),
            ctx.thread_max,
        )
        author = (pin.core.author or {}).get("login")
        before = pin_mentions_all(pin)
        replied: OpenPin | ReviewPin | DonePin
        match event:
            case ThreadFull():
                return event, False
            case PinReopened():
                replied = reopen_request(pin, event)
                pins[i] = replied
                r = replied.record
                msg = r["thread"][-1]
                _reopen_notices(ctx, r, actor, ment, msg, evs)
                # Everyone else tagged on the pin earlier would have heard of a plain reply (replied) - reopening must
                # not silence them.
                evs.append(
                    ctx.make_event(
                        "replied", r, actor, [lg for lg in sorted(before) if lg != author and lg not in ment], msg=msg
                    )
                )
            case Replied():
                replied = _with_reply(pin, event)
                pins[i] = replied
                r = replied.record
                msg = r["thread"][-1]
                # Every @-tag in this reply is a mention, even for someone tagged earlier on the pin - otherwise a
                # second "@Bob ..." reaches nobody (observed). Everyone else involved gets replied - never both.
                evs.append(ctx.make_event("mention", r, actor, ment, msg=msg))
                evs.append(
                    ctx.make_event(
                        "replied", r, actor, [lg for lg in [author] + sorted(before) if lg not in ment], msg=msg
                    )
                )
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

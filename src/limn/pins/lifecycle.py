"""How a pin changes state: transitions that take the state they apply to and return the next one.

Every function here is pure. Time arrives as the already-formatted string the store records (now_str()
in server.py), and actors arrive parsed. An outcome the caller must answer is a returned value in the
annotation, never an exception (docs/handbook/code-style-roadmap.md R1, R3).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from limn.pins.model import Actor, Agent, DonePin, OpenPin, Person, Pin, Record, ReviewPin

# The in-progress marker's fields (docs/handbook/api.md §처리 중 표시); a close clears them.
CLAIM_FIELDS = ("claimed_by", "claimed_at", "claim_ts", "claim_until", "eta_ts")
# What a reopen forgets: the last close (reply, ref, recorded changes) and any review or confirmation of it.
CLOSE_FIELDS = ("close_reply", "close_ref", "changes", "changes_at", "review", "confirmed_by", "confirmed_at")


@dataclass(frozen=True)
class AgentCannotConfirm:
    """Only a person may confirm: review exists to record that a person looked at an agent's closed pin."""


@dataclass(frozen=True)
class PinStillOpen:
    """An open pin has nothing to confirm; the pin travels along for the 409 body."""
    pin: OpenPin


@dataclass(frozen=True)
class AlreadyDone:
    """The pin is already done; confirming it again changes nothing and is not an error."""
    pin: DonePin


def confirmer(actor: Actor) -> Person | AgentCannotConfirm:
    """The person who may confirm, or the refusal for an agent - decided before any pin is loaded."""
    match actor:
        case Person():
            return actor
        case Agent():
            return AgentCannotConfirm()


def confirm(pin: Pin, by: Person, at: str) -> DonePin | AlreadyDone | PinStillOpen:
    """Confirm a pin awaiting review; a done pin comes back as AlreadyDone and an open one as PinStillOpen."""
    match pin:
        case ReviewPin():
            return confirm_review(pin, by, at)
        case DonePin():
            return AlreadyDone(pin)
        case OpenPin():
            return PinStillOpen(pin)


def confirm_review(pin: ReviewPin, by: Person, at: str) -> DonePin:
    """Close the review: drop the review flag, record who confirmed and when, add an ev=confirm thread entry, bump rev.

    Fields keep their order in the record (new ones go to the end), so the stored line changes only where the
    old in-place update changed it.
    """
    record = {key: value for key, value in pin.record.items() if key != "review"}
    record["confirmed_by"] = signature(by)
    record["confirmed_at"] = at
    record["thread"] = [*thread_of(pin.record), thread_message(pin.record.get("thread"), author(by), at, ev="confirm")]
    record["rev"] = next_rev(pin.record)
    return DonePin(record)


@dataclass(frozen=True)
class CloseRequest:
    """What a close carries, validated at the boundary: reply and ref texts, the changed ranges, and the review choice.

    review None leaves the choice to the closer: an agent's close awaits review, a person's is done at once.
    """
    reply: str | None = None
    ref: str | None = None
    changes: tuple[Record, ...] = ()
    review: bool | None = None


@dataclass(frozen=True)
class PinClosed:
    """The fact that an open pin was closed: by whom, when, with which reply, ref and changes, and whether it awaits review."""
    by: Actor
    at: str
    reply: str | None
    ref: str | None
    changes: tuple[Record, ...]
    review: bool


@dataclass(frozen=True)
class AlreadyClosed:
    """The pin was closed before; closing again changes nothing, so the first closer and reply stay on record."""
    pin: ReviewPin | DonePin


def decide_close(pin: Pin, by: Actor, at: str, request: CloseRequest) -> PinClosed | AlreadyClosed:
    """What closing does: an open pin is closed (into review when an agent closes it, unless the request says),
    a closed one is left alone."""
    match pin:
        case OpenPin():
            review = request.review if request.review is not None else isinstance(by, Agent)
            return PinClosed(by, at, request.reply, request.ref, request.changes, review)
        case ReviewPin() | DonePin():
            return AlreadyClosed(pin)


def evolve_close(pin: Pin, event: PinClosed) -> ReviewPin | DonePin:
    """Apply a close: done, done_at, closed_by, reply/ref/changes when given, review when chosen, an ev=close
    thread entry, the claim cleared, rev bumped. changes_at equals done_at, tying the changes to this close."""
    record = dict(pin.record)
    record["done"] = True
    record["done_at"] = event.at
    record["closed_by"] = signature(event.by)
    if event.reply:
        record["close_reply"] = event.reply
    if event.ref:
        record["close_ref"] = event.ref
    if event.changes:
        record["changes"] = [dict(change) for change in event.changes]
        record["changes_at"] = event.at
    if event.review:
        record["review"] = True
    record["thread"] = [*thread_of(pin.record),
                        thread_message(pin.record.get("thread"), author(event.by), event.at, event.reply or "",
                                       ev="close", ref=event.ref)]
    for key in CLAIM_FIELDS:
        record.pop(key, None)
    record["rev"] = next_rev(pin.record)
    return ReviewPin(record) if record.get("review") is True else DonePin(record)   # parse_pin()'s rule, done now true


@dataclass(frozen=True)
class PinReopened:
    """The fact that a pin was reopened: by whom, when, why, whom the reason tags, and whether it had been closed."""
    by: Actor
    at: str
    reason: str | None
    mentions: tuple[str, ...]
    was_closed: bool


def decide_reopen(pin: Pin, by: Actor, at: str, reason: str | None, mentions: tuple[str, ...]) -> PinReopened:
    """What reopening does. Reopening is always allowed; only a pin that was closed gets a thread entry and notices."""
    return PinReopened(by, at, reason, mentions, was_closed=not isinstance(pin, OpenPin))


def evolve_reopen(pin: Pin, event: PinReopened) -> OpenPin:
    """Apply a reopen: done false, who and when, the last close and its review/confirmation forgotten, and - if the pin
    had been closed - an ev=reopen thread entry carrying the reason and its mentions. rev is the caller's: a reopen
    request bumps it here via reopen_request(), a reopening reply bumps it once for the reply."""
    record = dict(pin.record)
    record["done"] = False
    record["reopened_at"] = event.at
    record["reopened_by"] = signature(event.by)
    for key in CLOSE_FIELDS:
        record.pop(key, None)
    if event.was_closed:
        record["thread"] = [*thread_of(pin.record),
                            thread_message(pin.record.get("thread"), author(event.by), event.at, event.reason or "",
                                           ev="reopen", mentions=event.mentions)]
    return OpenPin(record)


def reopen_request(pin: Pin, event: PinReopened) -> OpenPin:
    """POST /reopen: apply the reopen and bump rev - even for a pin that was already open, as before."""
    opened = evolve_reopen(pin, event)
    return OpenPin({**opened.record, "rev": next_rev(pin.record)})


def next_rev(record: Record) -> int:
    """The revision after a change: the store's rule counts a missing or empty rev as 0."""
    return int(record.get("rev") or 0) + 1


def signature(by: Actor) -> dict[str, str]:
    """How an actor is recorded on a pin (closed_by, confirmed_by, reopened_by): login and name."""
    return {"login": by.login, "name": by.name}


def author(by: Actor) -> dict[str, str]:
    """How an actor is written into a thread entry: its signature, plus a person's pic when there is one."""
    out = signature(by)
    if isinstance(by, Person) and by.pic:
        out["pic"] = by.pic
    return out


def thread_of(record: Record) -> list[Any]:
    """The record's thread as a list; a missing or malformed thread counts as empty."""
    thread = record.get("thread")
    return list(thread) if isinstance(thread, list) else []


def thread_message(thread: Sequence[Any] | None, by: dict[str, str], at: str, text: str = "", ev: str | None = None,
                   ref: str | None = None, mentions: Sequence[str] | None = None) -> dict[str, Any]:
    """The next thread entry: its id is one past the largest integer id already there (ids are never reused).

    ev marks a state-transition record (close, reopen, confirm); ref and mentions are kept only when given.
    """
    entries = thread if isinstance(thread, list) else []
    mid = max((m.get("id", 0) for m in entries if isinstance(m, dict) and _is_int(m.get("id"))), default=0) + 1
    msg: dict[str, Any] = {"id": mid, "by": by, "at": at, "text": text or ""}
    if ev:
        msg["ev"] = ev
    if ref:
        msg["ref"] = ref
    if mentions:
        msg["mentions"] = list(mentions)
    return msg


def _is_int(value: object) -> bool:
    """An int that is not a bool - how stored ids and revisions are recognised."""
    return isinstance(value, int) and not isinstance(value, bool)

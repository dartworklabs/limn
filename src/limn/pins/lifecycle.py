"""How a pin changes state: transitions that take the state they apply to and return the next one.

Every function here is pure. Time arrives as the already-formatted string the store records (now_str()
in server.py), and actors arrive parsed. An outcome the caller must answer is a returned value in the
annotation, never an exception (docs/handbook/code-style-roadmap.md R1, R3).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeGuard, TypeVar, cast

from limn.pins.model import (
    Actor, Agent, Claim, DonePin, OpenPin, Person, Pin, Record, ReviewPin, TrashedPin, parse_pin,
)

PinT = TypeVar("PinT", OpenPin, ReviewPin, DonePin)

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
    return DonePin.from_record(record)


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
    if record.get("review") is True:                 # parse_pin()'s rule, done now true
        return ReviewPin.from_record(record)
    return DonePin.from_record(record)


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
    return OpenPin.from_record(record)


def reopen_request(pin: Pin, event: PinReopened) -> OpenPin:
    """POST /reopen: apply the reopen and bump rev - even for a pin that was already open, as before."""
    opened = evolve_reopen(pin, event)
    return OpenPin.from_record({**opened.record, "rev": next_rev(pin.record)})


@dataclass(frozen=True)
class Replied:
    """The fact of a plain reply: by whom, when, the text, and whom it @-tags."""
    by: Actor
    at: str
    text: str
    mentions: tuple[str, ...]


@dataclass(frozen=True)
class ThreadFull:
    """The thread already holds as many replies as a pin may have; the conversation continues on a new pin."""
    limit: int


def reopens_on_reply(pin: Pin, human: bool, mentioned: Sequence[str], reopen: bool | None) -> bool:
    """Does a reply reopen this pin? The one rule behind the viewer's single [Reply] (docs/handbook/api.md §스레드 (답글)).

    An open pin never changes. Otherwise an explicit `reopen` (true/false, from the request) decides; without one, a
    human's reply on a pin awaiting review or done reopens it - the reply becomes the rework instruction - unless it
    tags a person (then it is a conversation with that person) or the pin is a question (then the reply is an answer).
    An agent's reply never reopens by the rule. `mentioned` is the post's resolved @-tags of people, without the poster.
    The viewer's preview (replyReopens) mirrors this function.
    """
    match pin:
        case OpenPin():
            return False
        case ReviewPin() | DonePin():
            if reopen is not None:
                return bool(reopen)
            if pin.record.get("kind_req") == "question" or not human:
                return False
            return not mentioned


def decide_reply(pin: Pin, by: Actor, at: str, text: str, mentions: tuple[str, ...], reopens: bool,
                 limit: int) -> PinReopened | Replied | ThreadFull:
    """What a reply does: reopen the pin with the reply as the reason, refuse when the thread is full, or add a reply.

    A reopening reply is not counted against the limit - it is recorded as a state-transition entry, like a close.
    """
    if reopens:
        return decide_reopen(pin, by, at, text, mentions)
    if len(replies_of(pin.record)) >= limit:
        return ThreadFull(limit)
    return Replied(by, at, text, mentions)


def evolve_reply(pin: PinT, event: Replied) -> PinT:
    """Apply a plain reply: one thread entry with its mentions, and rev bumped. The pin keeps its state."""
    record = dict(pin.record)
    record["thread"] = [*thread_of(pin.record),
                        thread_message(pin.record.get("thread"), author(event.by), event.at, event.text,
                                       mentions=event.mentions)]
    record["rev"] = next_rev(pin.record)
    return type(pin).from_record(record)


def replies_of(record: Record) -> list[Any]:
    """The thread's replies, without state-transition entries (ev close/reopen/confirm)."""
    return [m for m in thread_of(record) if isinstance(m, dict) and not m.get("ev")]


@dataclass(frozen=True)
class ClaimRequest:
    """A validated claim body: minutes until the marker lapses, and the optional estimate of the work."""
    ttl_min: int
    eta_min: int | None = None


@dataclass(frozen=True)
class ClaimClosedPin:
    """A closed pin cannot be claimed; the pin travels along for the 409 body."""
    pin: ReviewPin | DonePin


@dataclass(frozen=True)
class ClaimedByOther:
    """Someone else holds a live claim; the 409 body tells who, until when, and their estimate."""
    claimed_by: Any
    claim_until: Any
    eta_ts: Any


@dataclass(frozen=True)
class NotClaimed:
    """Unclaiming a pin that had no claim changes nothing; the pin is shown with any stray claim field cleared."""
    pin: Pin


def claim_holds(record: Record, now: float) -> bool:
    """Does the record carry an unexpired claim at epoch `now`? claim_until is epoch seconds, independent of timezone."""
    until = record.get("claim_until")
    return _is_num(until) and float(until) > now


def claim(pin: Pin, by: Actor, now: float, at: str, request: ClaimRequest,
          legacy_start: float | None) -> OpenPin | ClaimClosedPin | ClaimedByOther:
    """Place or extend the in-progress marker on an open pin; a closed pin is refused.

    now is epoch seconds and at the same moment as the store's time string. legacy_start is the epoch of an old
    claim's claimed_at, used only to backfill claim_ts when extending a claim written before claim_ts existed.
    """
    match pin:
        case OpenPin():
            return claim_open(pin, by, now, at, request, legacy_start)
        case ReviewPin() | DonePin():
            return ClaimClosedPin(pin)


def claim_open(pin: OpenPin, by: Actor, now: float, at: str, request: ClaimRequest,
               legacy_start: float | None) -> OpenPin | ClaimedByOther:
    """An open pin's claim rule: another identity's live claim refuses; the same identity extends; otherwise a new claim.

    An extension keeps the start (claimed_at/claim_ts) and re-measures claim_until from now; eta_ts is reset only when
    an estimate is given. A new claim drops every earlier claim field first - stray ones kept among the pin's fields
    too - so a stale estimate never survives.
    """
    held = pin.claim if pin.claim is not None and pin.claim.holds(now) else None
    if held is not None and held.by.get("login") != by.login:
        return ClaimedByOther(held.by, held.until, held.eta)
    record = dict(pin.record)
    if held is None:
        for key in CLAIM_FIELDS:
            record.pop(key, None)
        record["claimed_at"] = at
        record["claim_ts"] = now
    elif held.start is None:
        record["claim_ts"] = legacy_start or now
    record["claimed_by"] = signature(by)
    record["claim_until"] = now + request.ttl_min * 60
    if request.eta_min is not None:
        record["eta_ts"] = now + request.eta_min * 60
    record["rev"] = next_rev(pin.record)
    return OpenPin.from_record(record)


def unclaim(pin: Pin) -> OpenPin | NotClaimed:
    """Clear the in-progress marker, whoever asks (the trust model restricts nothing here); rev goes up only if there was one.

    Only an open pin can hold a claim. Any other pin, or an open one without a claim, comes back as NotClaimed, shown
    with every stray claim field (one kept among its fields, not a claim) cleared; nothing is written for it.
    """
    cleared = {key: value for key, value in pin.record.items() if key not in CLAIM_FIELDS}
    match pin:
        case OpenPin(claim=Claim()):
            cleared["rev"] = next_rev(pin.record)
            return OpenPin.from_record(cleared)
        case OpenPin() | ReviewPin() | DonePin():
            return NotClaimed(type(pin).from_record(cleared))


@dataclass(frozen=True)
class NotInTrash:
    """The Trash has no unexpired copy of this pin id."""
    pid: int


@dataclass(frozen=True)
class AlreadyLive:
    """A pin with this id is live again (restored before, or never deleted); restoring would duplicate it."""
    pid: int


def drop(pin: Pin, by: Actor, at: str) -> TrashedPin:
    """The Trash copy of a deleted pin: its record without the claim (never left behind), stamped with who and when."""
    record = {key: value for key, value in pin.record.items() if key not in CLAIM_FIELDS}
    record["dropped_at"] = at
    record["dropped_by"] = signature(by)
    return TrashedPin.from_record(record)


def find_trashed(trash: Sequence[Record], pid: int) -> TrashedPin | NotInTrash:
    """The newest copy of pin pid among the Trash entries given (the caller passes only unexpired ones)."""
    hits = [record for record in trash if record.get("id") == pid]
    return TrashedPin.from_record(hits[-1]) if hits else NotInTrash(pid)


def restore(trashed: TrashedPin, live: bool, by: Actor, at: str) -> Pin | AlreadyLive:
    """Bring a Trash copy back as the pin it was: dropped_at/by removed, restored_at/by recorded, rev bumped.

    live says whether the id is already among the live pins; then nothing is restored.
    """
    if live:
        # A Trash copy carries the id find_trashed() matched; the cast informs the checker, the value is as stored.
        return AlreadyLive(cast(int, trashed.record.get("id")))
    record = {key: value for key, value in trashed.record.items() if key not in ("dropped_at", "dropped_by")}
    record["restored_at"] = at
    record["restored_by"] = signature(by)
    record["rev"] = next_rev(trashed.record)
    return parse_pin(record)


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


def _is_num(value: object) -> TypeGuard[int | float]:
    """An int or float that is not a bool - how stored epoch times are recognised."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: object) -> bool:
    """An int that is not a bool - how stored ids and revisions are recognised."""
    return isinstance(value, int) and not isinstance(value, bool)

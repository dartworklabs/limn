"""Shared pure pin thread, revision and claim display primitives."""

from collections.abc import Sequence
from typing import Any, TypeVar

from limn.pins.model import Actor, DonePin, OpenPin, Person, Record, ReviewPin, ThreadEntry, ThreadEv, claim_unexpired

PinT = TypeVar("PinT", OpenPin, ReviewPin, DonePin)


# The in-progress marker fields are shared by closing, claims and trash transitions.
CLAIM_FIELDS = ("claimed_by", "claimed_at", "claim_ts", "claim_until", "eta_ts")


def claim_holds(record: Record, now: float) -> bool:
    """Does the stored record show an unexpired claim at epoch `now`? claim_unexpired() on its claim_until alone.

    pins.md's in-progress marker and GET /api/pins's backfilled claim_ts read the record this way, not through the
    lifted Claim.holds, and the difference is kept on purpose (both answers are the agent contract): a hand-edited
    record whose claim_until has no claimed_by object, or whose closed state still carries claim fields, shows the
    claim here while it is no claim for POST /claim. This server never writes either shape.
    """
    return claim_unexpired(record.get("claim_until"), now)


def rev_after(rev: int | None) -> int:
    """The revision after a change to a pin at `rev` (PinCore.rev): a missing rev counts as 0."""
    return (rev or 0) + 1


def signature(by: Actor) -> dict[str, str]:
    """How an actor is recorded on a pin (closed_by, confirmed_by, reopened_by): login and name."""
    return {"login": by.login, "name": by.name}


def author(by: Actor) -> dict[str, str]:
    """How an actor is written into a thread entry: its signature, plus a person's pic when there is one."""
    out = signature(by)
    if isinstance(by, Person) and by.pic:
        out["pic"] = by.pic
    return out


def thread_message(
    thread: Sequence[ThreadEntry] | None,
    by: dict[str, str],
    at: str,
    text: str = "",
    ev: ThreadEv | None = None,
    ref: str | None = None,
    mentions: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The next thread entry, as stored: its id is one past the largest integer id already in thread (ids are never
    reused; no thread counts as empty).

    ev marks a state-transition record (close, reopen, confirm, assign); ref and mentions are kept only when given.
    """
    mid = max((entry.id for entry in thread or () if entry.id is not None), default=0) + 1
    msg: dict[str, Any] = {"id": mid, "by": by, "at": at, "text": text or ""}
    if ev:
        msg["ev"] = ev
    if ref:
        msg["ref"] = ref
    if mentions:
        msg["mentions"] = list(mentions)
    return msg


def with_entry(thread: Sequence[ThreadEntry] | None, message: Record) -> list[Any]:
    """The stored thread with `message` (thread_message's) appended: every earlier entry written back as stored."""
    return [*(entry.record for entry in thread or ()), message]


def round_marks(thread: Sequence[ThreadEntry] | None) -> tuple[int, int]:
    """(last close, last reopen): the positions in a pin's thread (PinCore.thread; none counts as empty) of the latest
    ev=close and the latest ev=reopen entry, -1 for none. The one scan behind a pin's current round -
    limn.pins.mentions.thread_round() and pin_reopened_in_round() both read it, so the round and pins.md's "reopened"
    marker cannot disagree. ev is typed (ThreadEv), so a misspelt mark is a type error."""
    last_close = last_reopen = -1
    for index, entry in enumerate(thread or ()):
        if entry.ev == "close":
            last_close = index
        elif entry.ev == "reopen":
            last_reopen = index
    return last_close, last_reopen


def pin_reopened_in_round(thread: Sequence[ThreadEntry] | None) -> bool:
    """Has the pin whose thread this is been reopened since it was last closed - the latest ev=reopen entry comes
    after the latest ev=close one (none counts as before everything), whatever follows it (a confirm, replies)? Drives
    pins.md's "reopened" marker (§Pending review); the current round then starts at that reopen
    (limn.pins.mentions.thread_round)."""
    last_close, last_reopen = round_marks(thread)
    return last_reopen > last_close

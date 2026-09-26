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
    record["confirmed_by"] = {"login": by.login, "name": by.name}
    record["confirmed_at"] = at
    record["thread"] = [*thread_of(pin.record), thread_message(pin.record.get("thread"), author(by), at, ev="confirm")]
    record["rev"] = int(pin.record.get("rev") or 0) + 1         # the store's rule: a missing or empty rev counts as 0
    return DonePin(record)


def author(by: Person) -> dict[str, str]:
    """How a person is written into a thread entry: login and name, plus pic when there is one."""
    out = {"login": by.login, "name": by.name}
    if by.pic:
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

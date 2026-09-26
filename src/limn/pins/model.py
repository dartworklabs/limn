"""What a pin and an actor can be: state types parsed from stored records, and the typed miss of a load.

A stored pin is a JSON record (docs/handbook/api.md §핀 레코드). Its state is not a stored field; it follows
from done/review exactly as pin_state() in server.py computes it. Each state is its own type holding the
record unchanged, so a transition can only be called on the state it applies to, and every field the
server does not model here - including ones an older or newer version wrote - survives a round trip.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

Record: TypeAlias = Mapping[str, Any]


@dataclass(frozen=True)
class OpenPin:
    """A pin nobody has closed: its stored done is false or missing."""
    record: Record


@dataclass(frozen=True)
class ReviewPin:
    """Closed by an agent and waiting for a person to confirm it: done and review are both true."""
    record: Record


@dataclass(frozen=True)
class DonePin:
    """Closed for good. A legacy done record with no review field is done too."""
    record: Record


Pin: TypeAlias = OpenPin | ReviewPin | DonePin


def parse_pin(record: Record) -> Pin:
    """The state type of a stored record, by the rule of pin_state(): not done is open; done with review is review."""
    if not record.get("done"):
        return OpenPin(record)
    if record.get("review") is True:
        return ReviewPin(record)
    return DonePin(record)


@dataclass(frozen=True)
class Person:
    """A human actor as stored in pins: login, display name, and an optional avatar URL for thread entries."""
    login: str
    name: str
    pic: str | None = None


@dataclass(frozen=True)
class Agent:
    """A non-human actor: a headerless loopback request or an API-token principal."""
    login: str
    name: str


Actor: TypeAlias = Person | Agent


@dataclass(frozen=True)
class PinNotFound:
    """No pin with this id is in the store; the API answers ok:false rather than an error."""
    pid: int

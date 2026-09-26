"""What a pin and an actor can be: state types parsed from stored records, and the typed miss of a load.

A stored pin is a JSON record (docs/handbook/api.md §핀 레코드). Its state is not a stored field; it follows
from done/review exactly as pin_state() in server.py computes it. Each state type lifts the fields only that state
has into typed attributes - an open pin's claim, a closed pin's close, a done pin's confirmation, a Trash copy's
drop - so a claim on a closed pin or a confirmation on an open one has no attribute to live in. Every other field,
including ones an older or newer version wrote, is kept as stored (`fields`), and `record` writes the pin back in
the stored field order: a record parsed and written back unchanged gives the same JSON line, byte for byte.

Parsing is lenient, as the store has always been: a legacy record may lack any of these fields, and a lifted field
whose stored value is not of the expected kind is not lifted - it stays among `fields` exactly as stored, and the
state reads as if it were absent. The transitions in lifecycle.py and edit.py still build the next record field by
field, because the stored order is part of the byte contract, and parse it into the next state at once.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias, TypeVar

Record: TypeAlias = Mapping[str, Any]
# An actor as a pin records it (claimed_by, closed_by, confirmed_by, dropped_by): {login, name} as
# lifecycle.signature() writes it, kept as stored so a field this version does not know survives.
Signature: TypeAlias = Mapping[str, Any]
# A lifted group's table: stored key -> (attribute name, does a stored value have the kind the attribute holds).
Shapes: TypeAlias = Mapping[str, tuple[str, Callable[[object], bool]]]


def _is_text(value: object) -> bool:
    """A string - how every *_at time and the close's reply and ref are stored."""
    return isinstance(value, str)


def _is_signature(value: object) -> bool:
    """A JSON object - the stored form of an actor."""
    return isinstance(value, Mapping)


def _is_epoch(value: object) -> bool:
    """An int or float that is not a bool - how claim_ts, claim_until and eta_ts are stored (epoch seconds)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_changes(value: object) -> bool:
    """A list of JSON objects - the stored form of a close's changed ranges ([{file, lo, hi}])."""
    return isinstance(value, list) and all(isinstance(change, Mapping) for change in value)


@dataclass(frozen=True)
class Claim:
    """The in-progress marker on an open pin (docs/handbook/api.md §처리 중 표시).

    by is claimed_by, the field that makes a claim; at is claimed_at (the store's time string); start, until and eta
    are claim_ts, claim_until and eta_ts in epoch seconds, as stored (an int stays an int). A claim written before
    claim_ts existed has no start, and one without a usable claim_until has lapsed.
    """
    by: Signature
    at: str | None = None
    start: float | None = None
    until: float | None = None
    eta: float | None = None

    def holds(self, now: float) -> bool:
        """Is the claim unexpired at epoch `now`? claim_until is epoch seconds, independent of timezone."""
        return self.until is not None and self.until > now


CLAIM_SHAPES: Shapes = {"claimed_by": ("by", _is_signature), "claimed_at": ("at", _is_text),
                        "claim_ts": ("start", _is_epoch), "claim_until": ("until", _is_epoch),
                        "eta_ts": ("eta", _is_epoch)}


@dataclass(frozen=True)
class Close:
    """How a closed pin was closed: done_at, closed_by, and what the closer left - close_reply, close_ref, changes.

    Every part may be missing: a close from before a field existed lacks it, and reply, ref and changes are optional
    in a close request. changes_at is the done_at of the close that recorded the changes (api.md §핀 단위 변경 보기).
    """
    at: str | None = None
    by: Signature | None = None
    reply: str | None = None
    ref: str | None = None
    changes: Sequence[Record] | None = None
    changes_at: str | None = None


CLOSE_SHAPES: Shapes = {"done_at": ("at", _is_text), "closed_by": ("by", _is_signature),
                        "close_reply": ("reply", _is_text), "close_ref": ("ref", _is_text),
                        "changes": ("changes", _is_changes), "changes_at": ("changes_at", _is_text)}


@dataclass(frozen=True)
class Confirmation:
    """The person who confirmed a pin that awaited review, and when (confirmed_by, confirmed_at)."""
    by: Signature
    at: str


CONFIRMATION_SHAPES: Shapes = {"confirmed_by": ("by", _is_signature), "confirmed_at": ("at", _is_text)}


@dataclass(frozen=True)
class Dropped:
    """Who deleted a pin into the Trash, and when (dropped_by, dropped_at); dropped_at also dates the copy's expiry."""
    at: str
    by: Signature


DROPPED_SHAPES: Shapes = {"dropped_at": ("at", _is_text), "dropped_by": ("by", _is_signature)}

GroupT = TypeVar("GroupT", Claim, Close, Confirmation, Dropped)


def _taken(record: Record, shapes: Shapes) -> dict[str, Any]:
    """The group's fields that record stores with the expected kind, keyed by attribute name."""
    return {attr: record[key] for key, (attr, fits) in shapes.items() if key in record and fits(record[key])}


def _lift(record: Record, shapes: Shapes, group: type[GroupT], required: Sequence[str]) -> GroupT | None:
    """The group's value from record; None when one of the `required` attributes is missing or of the wrong kind -
    then none of the group's fields is lifted and all of them stay among the kept fields as stored."""
    taken = _taken(record, shapes)
    if any(attr not in taken for attr in required):
        return None
    return group(**taken)


def _stored(value: Claim | Close | Confirmation | Dropped | None, shapes: Shapes) -> dict[str, Any]:
    """A lifted group back as stored fields: each attribute that is set, under its stored key, in table order."""
    if value is None:
        return {}
    return {key: getattr(value, attr) for key, (attr, _) in shapes.items() if getattr(value, attr) is not None}


def _others(record: Record, lifted: Record) -> dict[str, Any]:
    """The record's fields that were not lifted, in stored order."""
    return {key: value for key, value in record.items() if key not in lifted}


def _render(fields: Record, order: Sequence[str], lifted: Record) -> dict[str, Any]:
    """The stored record: every field in the place `order` gives it, the lifted ones from the state and the rest as
    kept. Fields `order` does not name (a state built in code rather than parsed) follow in fields-then-lifted order."""
    merged = {**fields, **lifted}
    return {**{key: merged[key] for key in order if key in merged}, **merged}


def _check(state: object, fields: Record, lifted: Record) -> None:
    """Guard a state built from trusted data: its stored done/review must name this very state, and a lifted field
    must not also sit among the kept ones (writing the record back would have to pick one). A violation is a defect."""
    if _state_of(fields) is not type(state):
        raise ValueError("%s cannot hold done=%r, review=%r" % (type(state).__name__, fields.get("done"),
                                                                 fields.get("review")))
    if lifted.keys() & fields.keys():
        raise ValueError("%s lifts %s but also keeps it" % (type(state).__name__, sorted(lifted.keys() & fields.keys())))


@dataclass(frozen=True)
class OpenPin:
    """A pin nobody has closed: its stored done is false or missing. Only an open pin carries a claim.

    A pin reopened after a close keeps that close's done_at/closed_by among its fields - the history of an earlier
    close, not a close of this pin; claim fields without a claimed_by object are kept there too and are no claim.
    """
    claim: Claim | None
    fields: Record
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject a stored done that says closed, or a claim field held twice."""
        _check(self, self.fields, _stored(self.claim, CLAIM_SHAPES))

    @classmethod
    def from_record(cls, record: Record) -> OpenPin:
        """The open pin a stored record describes; ValueError if its done says it is closed."""
        claim = _lift(record, CLAIM_SHAPES, Claim, required=("by",))
        return cls(claim, _others(record, _stored(claim, CLAIM_SHAPES)), tuple(record))

    @property
    def record(self) -> dict[str, Any]:
        """The pin as stored: a new dict in stored field order, the claim written back where it was."""
        return _render(self.fields, self.order, _stored(self.claim, CLAIM_SHAPES))


@dataclass(frozen=True)
class ReviewPin:
    """Closed by an agent and waiting for a person to confirm it: done and review are both true. It has a close and
    no claim; a confirmation comes only with the move to done."""
    close: Close
    fields: Record
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject stored done/review that do not say awaiting review, or a close field held twice."""
        _check(self, self.fields, _stored(self.close, CLOSE_SHAPES))

    @classmethod
    def from_record(cls, record: Record) -> ReviewPin:
        """The pin awaiting review a stored record describes; ValueError unless done and review are true."""
        close = Close(**_taken(record, CLOSE_SHAPES))
        return cls(close, _others(record, _stored(close, CLOSE_SHAPES)), tuple(record))

    @property
    def record(self) -> dict[str, Any]:
        """The pin as stored: a new dict in stored field order, the close written back where it was."""
        return _render(self.fields, self.order, _stored(self.close, CLOSE_SHAPES))


@dataclass(frozen=True)
class DonePin:
    """Closed for good: done without review. It has a close, a confirmation when a person confirmed it out of review,
    and no claim. A legacy done record with no review field is done too."""
    close: Close
    confirmation: Confirmation | None
    fields: Record
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject stored done/review that do not say done, or a close or confirmation field held twice."""
        _check(self, self.fields, {**_stored(self.close, CLOSE_SHAPES),
                                   **_stored(self.confirmation, CONFIRMATION_SHAPES)})

    @classmethod
    def from_record(cls, record: Record) -> DonePin:
        """The done pin a stored record describes; ValueError unless done is set and review is not true. A
        confirmation is lifted only whole - confirmed_by an object and confirmed_at a string."""
        close = Close(**_taken(record, CLOSE_SHAPES))
        confirmation = _lift(record, CONFIRMATION_SHAPES, Confirmation, required=("by", "at"))
        lifted = {**_stored(close, CLOSE_SHAPES), **_stored(confirmation, CONFIRMATION_SHAPES)}
        return cls(close, confirmation, _others(record, lifted), tuple(record))

    @property
    def record(self) -> dict[str, Any]:
        """The pin as stored: a new dict in stored field order, close and confirmation written back where they were."""
        return _render(self.fields, self.order, {**_stored(self.close, CLOSE_SHAPES),
                                                 **_stored(self.confirmation, CONFIRMATION_SHAPES)})


Pin: TypeAlias = OpenPin | ReviewPin | DonePin


def _state_of(record: Record) -> type[OpenPin] | type[ReviewPin] | type[DonePin]:
    """The state a stored record is in, by the rule of pin_state(): not done is open; done with review true is review."""
    if not record.get("done"):
        return OpenPin
    if record.get("review") is True:
        return ReviewPin
    return DonePin


def parse_pin(record: Record) -> Pin:
    """The state type of a stored record, by the rule of pin_state(), with that state's fields lifted. Never fails:
    any JSON object is some state, and whatever does not fit is kept as stored."""
    return _state_of(record).from_record(record)


@dataclass(frozen=True)
class TrashedPin:
    """A deleted pin in the Trash (pins.dropped.jsonl): the pin as it was, and who dropped it when - restorable by id.

    dropped is lifted only whole (dropped_at a string and dropped_by an object), as drop() always writes it.
    """
    pin: Pin
    dropped: Dropped | None
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject a drop field that the pin also holds."""
        twice = _stored(self.dropped, DROPPED_SHAPES).keys() & self.pin.record.keys()
        if twice:
            raise ValueError("TrashedPin lifts %s but the pin also keeps it" % sorted(twice))

    @classmethod
    def from_record(cls, record: Record) -> TrashedPin:
        """The Trash copy a stored entry describes: the drop lifted, the rest parsed as the pin it was."""
        dropped = _lift(record, DROPPED_SHAPES, Dropped, required=("at", "by"))
        return cls(parse_pin(_others(record, _stored(dropped, DROPPED_SHAPES))), dropped, tuple(record))

    @property
    def record(self) -> dict[str, Any]:
        """The entry as stored: a new dict in stored field order, the drop written back where it was."""
        return _render(self.pin.record, self.order, _stored(self.dropped, DROPPED_SHAPES))


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

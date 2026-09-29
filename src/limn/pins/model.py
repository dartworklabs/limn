"""What a pin and an actor can be: state types parsed from stored records, and the typed miss of a load.

A stored pin is a JSON record (docs/handbook/api.md §핀 레코드). Its state is not a stored field; it follows
from done/review (state_of), and the name the API shows for it is the state type's `state` (limn.pins.view.pin_state).
Every state holds the fields all pins share as one typed `core` (PinCore: id, document, place, note, author, rev,
kind_req, assignee, mentions, thread, and the line-matching state), and lifts the fields only that state has into
typed attributes - an open pin's claim, a closed pin's close, a done pin's confirmation, a Trash copy's drop - so a
claim on a closed pin or a confirmation on an open one has no attribute to live in. Every other field, including
ones an older or newer version wrote, is kept as stored (`fields`), and `record` writes the pin back in the stored
field order: a record parsed and written back unchanged gives the same JSON line, byte for byte.

Parsing is lenient, as the store has always been: a legacy record may lack any of these fields, and a lifted field
whose stored value is not of the expected kind is not lifted - it stays among `fields` exactly as stored, and the
pin reads as if it were absent. The transitions in lifecycle.py and edit.py read the typed attributes, and still
build the next record field by field, because the stored order is part of the byte contract, and parse it into the
next state at once.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, TypeAlias, TypeGuard, TypeVar, get_args

from limn.pins.shapes import is_int, is_num

Record: TypeAlias = Mapping[str, Any]
# The name of a pin's state as the API and pins.md show it (GET /api/pins `state`, docs/handbook/api.md §검토 대기).
StateName: TypeAlias = Literal["open", "review", "done"]
# An actor as a pin records it (claimed_by, closed_by, confirmed_by, dropped_by): {login, name} as
# lifecycle.signature() writes it, kept as stored so a field this version does not know survives.
Signature: TypeAlias = Mapping[str, Any]
# A lifted group's table: stored key -> (attribute name, does a stored value have the kind the attribute holds).
Shapes: TypeAlias = Mapping[str, tuple[str, Callable[[object], bool]]]
# kind_req: what a pin asks for - a fix (the default; every legacy pin is one) or an answer (docs/handbook/api.md §스레드).
KindReq: TypeAlias = Literal["fix", "question"]
KIND_REQS: tuple[KindReq, ...] = get_args(KindReq)
# The mark a thread entry may carry (ev): the close, reopen and confirm transitions (limn.features.pins.lifecycle.rules) and an
# assignee change (limn.features.pins.editing.rules). A reply has none. limn.pins.record accepts no other stored value.
ThreadEv: TypeAlias = Literal["close", "reopen", "confirm", "assign"]
THREAD_EVENTS: tuple[ThreadEv, ...] = get_args(ThreadEv)


def is_kind_req(v: object) -> TypeGuard[KindReq]:
    """Is v one of KIND_REQS? The check a request parser, the stored-record check and PinCore's lift share."""
    return v in KIND_REQS


def is_thread_ev(v: object) -> TypeGuard[ThreadEv]:
    """Is v one of THREAD_EVENTS - a mark a thread entry may carry? A string compare only (never a hash, so any
    stored JSON value may be asked)."""
    return isinstance(v, str) and v in THREAD_EVENTS


def _is_text(value: object) -> bool:
    """A string - how every *_at time and the close's reply and ref are stored."""
    return isinstance(value, str)


def _is_signature(value: object) -> bool:
    """A JSON object - the stored form of an actor."""
    return isinstance(value, Mapping)


def _is_object(value: object) -> bool:
    """A JSON object of any fields - how a line pin's anchor is stored (its shape is limn.mapping's)."""
    return isinstance(value, Mapping)


def _is_changes(value: object) -> bool:
    """A list of JSON objects - the stored form of a close's changed ranges ([{file, lo, hi}])."""
    return isinstance(value, list) and all(isinstance(change, Mapping) for change in value)


def _is_texts(value: object) -> bool:
    """A list of strings - how mentions (logins) are stored, on a pin and on a thread entry."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_bool(value: object) -> bool:
    """A JSON boolean - how stale is stored."""
    return isinstance(value, bool)


def _is_frac(value: object) -> TypeGuard[list[float]]:
    """Four JSON numbers in a list - how a region's frac ([x, y, w, h] as fractions of the page) is stored."""
    return isinstance(value, list) and len(value) == 4 and all(is_num(x) for x in value)


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
        """Is the claim unexpired at epoch `now`? The rule is claim_unexpired's, on this claim's until."""
        return claim_unexpired(self.until, now)


def claim_unexpired(until: object, now: float) -> bool:
    """The one expiry rule of a claim: is `until` (a stored claim_until) a JSON number of epoch seconds after epoch
    `now`? Epoch seconds are independent of timezone; a missing or non-numeric claim_until has lapsed."""
    return is_num(until) and until > now


CLAIM_SHAPES: Shapes = {
    "claimed_by": ("by", _is_signature),
    "claimed_at": ("at", _is_text),
    "claim_ts": ("start", is_num),
    "claim_until": ("until", is_num),
    "eta_ts": ("eta", is_num),
}


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


CLOSE_SHAPES: Shapes = {
    "done_at": ("at", _is_text),
    "closed_by": ("by", _is_signature),
    "close_reply": ("reply", _is_text),
    "close_ref": ("ref", _is_text),
    "changes": ("changes", _is_changes),
    "changes_at": ("changes_at", _is_text),
}


@dataclass(frozen=True)
class Confirmation:
    """The person who confirmed a pin that awaited review, and when (confirmed_by, confirmed_at)."""

    by: Signature
    at: str


CONFIRMATION_SHAPES: Shapes = {"confirmed_by": ("by", _is_signature), "confirmed_at": ("at", _is_text)}


@dataclass(frozen=True)
class Dropped:
    """When a pin was deleted into the Trash, and by whom (dropped_at, dropped_by); dropped_at also dates the copy's
    expiry. by is None for a hand-written copy without dropped_by - its dropped_at still dates it."""

    at: str
    by: Signature | None = None


DROPPED_SHAPES: Shapes = {"dropped_at": ("at", _is_text), "dropped_by": ("by", _is_signature)}

GroupT = TypeVar("GroupT", Claim, Close, Confirmation, Dropped)


def _fitting(record: Record, shapes: Shapes) -> dict[str, Any]:
    """The group's fields that record stores with the expected kind, under their stored keys, in table order."""
    return {key: record[key] for key, (_, fits) in shapes.items() if key in record and fits(record[key])}


def _taken(record: Record, shapes: Shapes) -> dict[str, Any]:
    """The group's fields that record stores with the expected kind, keyed by attribute name."""
    return {shapes[key][0]: value for key, value in _fitting(record, shapes).items()}


def _lift(record: Record, shapes: Shapes, group: type[GroupT], required: Sequence[str]) -> GroupT | None:
    """The group's value from record; None when one of the `required` attributes is missing or of the wrong kind -
    then none of the group's fields is lifted and all of them stay among the kept fields as stored."""
    taken = _taken(record, shapes)
    if any(attr not in taken for attr in required):
        return None
    return group(**taken)


def _stored(value: object, shapes: Shapes) -> dict[str, Any]:
    """A lifted group (a Claim, a Close, a PinCore ... or None) back as stored fields: each attribute of the table
    that is set, under its stored key, in table order."""
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
    if state_of(fields) is not type(state):
        raise ValueError(
            "%s cannot hold done=%r, review=%r" % (type(state).__name__, fields.get("done"), fields.get("review"))
        )
    if lifted.keys() & fields.keys():
        raise ValueError(
            "%s lifts %s but also keeps it" % (type(state).__name__, sorted(lifted.keys() & fields.keys()))
        )


@dataclass(frozen=True)
class ThreadEntry:
    """One entry of a pin's thread (docs/handbook/api.md §스레드 (답글)): a reply, or a state-transition mark (ev).

    id, by, at and text are what every entry this server writes has; ev marks a transition, ref is a close's
    reference and mentions the entry's @-tags, each only when given. Parsed like a pin: a part that is missing or of
    the wrong kind is not lifted and stays among `fields` as stored (an ev outside THREAD_EVENTS too), and `record`
    writes the entry back in its stored field order.
    """

    id: int | None = None
    by: Signature | None = None
    at: str | None = None
    text: str | None = None
    ev: ThreadEv | None = None
    ref: str | None = None
    mentions: Sequence[str] | None = None
    fields: Record = field(default_factory=dict)
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject a part held both lifted and kept (writing the entry back would have to pick one): a defect."""
        twice = _stored(self, THREAD_ENTRY_SHAPES).keys() & self.fields.keys()
        if twice:
            raise ValueError("ThreadEntry lifts %s but also keeps it" % sorted(twice))

    @classmethod
    def from_record(cls, entry: Record) -> ThreadEntry:
        """The entry a stored thread object describes; never fails."""
        taken = _taken(entry, THREAD_ENTRY_SHAPES)
        return cls(**taken, fields=_others(entry, _fitting(entry, THREAD_ENTRY_SHAPES)), order=tuple(entry))

    @property
    def record(self) -> dict[str, Any]:
        """The entry as stored: a new dict in stored field order."""
        return _render(self.fields, self.order, _stored(self, THREAD_ENTRY_SHAPES))


THREAD_ENTRY_SHAPES: Shapes = {
    "id": ("id", is_int),
    "by": ("by", _is_signature),
    "at": ("at", _is_text),
    "text": ("text", _is_text),
    "ev": ("ev", is_thread_ev),
    "ref": ("ref", _is_text),
    "mentions": ("mentions", _is_texts),
}


def _is_thread(value: object) -> TypeGuard[list[Record]]:
    """A list of JSON objects - a stored thread whose entries can be lifted one by one."""
    return isinstance(value, list) and all(isinstance(entry, Mapping) for entry in value)


@dataclass(frozen=True)
class LineSpan:
    """Where a line pin points: its .tex file (the absolute path as stored) and the lines lo..hi (1-based, inclusive).

    How it was placed there - name, the PDF page and frac it was dragged on, raw_lo/raw_hi, kind, via, score, scope,
    the build of its mark, file_rel - is lifted on the pin's core (PinCore); its quote is kept among the pin's fields.
    """

    file: str
    lo: int
    hi: int


@dataclass(frozen=True)
class Region:
    """Where a view-only PDF pin points (is_region_pin): the PDF (its path as stored), the page (1-based) and frac,
    the region as fractions of the page [x, y, w, h] - the stored list itself. Its pdf_build is lifted on the core and
    its quote kept among the pin's fields as stored."""

    pdf: str
    page: int
    frac: Sequence[float]


# Where a pin points: lines of a .tex file, or a region of a view-only PDF's page.
PinPlace: TypeAlias = LineSpan | Region


def _place_of(record: Record) -> PinPlace | None:
    """The place a stored record gives, lifted whole or not at all: a Region when the record is shaped as a region pin
    (is_region_pin) with an integer page and a four-number frac; a LineSpan when it is not and has a non-empty file
    string and integer lo and hi. None otherwise - then every one of those fields stays among the kept ones."""
    if is_region_pin(record):
        page, frac = record.get("page"), record.get("frac")
        if is_int(page) and _is_frac(frac):
            return Region(record["pdf"], page, frac)
        return None
    file, lo, hi = record.get("file"), record.get("lo"), record.get("hi")
    if isinstance(file, str) and file and is_int(lo) and is_int(hi):
        return LineSpan(file, lo, hi)
    return None


def _place_stored(place: PinPlace | None) -> dict[str, Any]:
    """A lifted place back as its stored fields."""
    match place:
        case LineSpan():
            return {"file": place.file, "lo": place.lo, "hi": place.hi}
        case Region():
            return {"pdf": place.pdf, "page": place.page, "frac": place.frac}
        case None:
            return {}


@dataclass(frozen=True)
class PinCore:
    """What a pin is whatever its state: the fields every state shares, typed (docs/handbook/api.md §핀 레코드).

    id; doc, the document key (a pin from before several documents has none); place; note; at and author, when and
    by whom it was made; rev (a missing rev counts as 0 wherever a rev is compared or bumped); kind_req (none is a
    fix); assignee; mentions, the note's @-tags; thread; the line-matching state - anchor (the head/tail text a line
    pin follows, kept as stored for limn.mapping), synced_at (epoch seconds), stale and sync; how the pin was placed -
    name (the file's name, or the PDF's), kind and scope (the rung of the range ladder), via and score (the path and
    score of the pick), raw_lo/raw_hi (the dragged lines before the ladder), a line pin's PDF mark (page and frac,
    the page and box it was dragged on - a region pin's are its place), pdf_build and the legacy frac_build (the build
    those coordinates belong to), file_rel (the file relative to the manuscript root, ADR-0006); and the edit marker
    (edited_at, edited_by). Each is lifted only when stored with its kind - mentions a list of strings, thread a list
    of objects (each a ThreadEntry), frac four numbers - and place only whole; anything else stays among the state's
    kept fields as stored, and the core reads it as absent. The quote is never lifted: the record check does not vouch
    for its kind, so readers take it as stored.
    """

    id: int | None = None
    doc: str | None = None
    place: PinPlace | None = None
    note: str | None = None
    at: str | None = None
    author: Signature | None = None
    rev: int | None = None
    kind_req: KindReq | None = None
    assignee: str | None = None
    mentions: Sequence[str] | None = None
    thread: Sequence[ThreadEntry] | None = None
    anchor: Record | None = None
    synced_at: float | None = None
    stale: bool | None = None
    sync: str | None = None
    name: str | None = None
    kind: str | None = None
    scope: str | None = None
    via: str | None = None
    score: float | None = None
    raw_lo: int | None = None
    raw_hi: int | None = None
    page: int | None = None
    frac: Sequence[float] | None = None
    pdf_build: str | None = None
    frac_build: str | None = None
    file_rel: str | None = None
    edited_at: str | None = None
    edited_by: Signature | None = None

    def __post_init__(self) -> None:
        """Reject a page or frac held both by a Region place and by the core (writing it back would have to pick one):
        a defect."""
        if isinstance(self.place, Region) and (self.page is not None or self.frac is not None):
            raise ValueError("PinCore holds page/frac beside a Region place")

    @classmethod
    def from_record(cls, record: Record) -> PinCore:
        """The shared fields a stored record holds with their kind; never fails. A Region place takes the record's
        page and frac, so the core lifts them only for another place."""
        thread = record.get("thread")
        place = _place_of(record)
        return cls(
            place=place,
            thread=tuple(ThreadEntry.from_record(entry) for entry in thread) if _is_thread(thread) else None,
            **_taken(record, REGION_CORE_SHAPES if isinstance(place, Region) else CORE_SHAPES),
        )

    @property
    def pid(self) -> int:
        """The pin's id. Every pin the store hands out has an integer one (limn.pins.record checks it); asking a pin
        built without one is a defect (ValueError)."""
        if self.id is None:
            raise ValueError("a pin without an id has no identity")
        return self.id

    def stored(self) -> dict[str, Any]:
        """The core back as stored fields, each one that is set: the table's in table order, then the place, then the
        thread with every entry written back as stored."""
        out = {**_stored(self, CORE_SHAPES), **_place_stored(self.place)}
        if self.thread is not None:
            out["thread"] = [entry.record for entry in self.thread]
        return out


# The core's plain fields (place and thread have their own rules in PinCore).
CORE_SHAPES: Shapes = {
    "id": ("id", is_int),
    "doc": ("doc", _is_text),
    "note": ("note", _is_text),
    "at": ("at", _is_text),
    "author": ("author", _is_signature),
    "rev": ("rev", is_int),
    "kind_req": ("kind_req", is_kind_req),
    "assignee": ("assignee", _is_text),
    "mentions": ("mentions", _is_texts),
    "anchor": ("anchor", _is_object),
    "synced_at": ("synced_at", is_num),
    "stale": ("stale", _is_bool),
    "sync": ("sync", _is_text),
    "name": ("name", _is_text),
    "kind": ("kind", _is_text),
    "scope": ("scope", _is_text),
    "via": ("via", _is_text),
    "score": ("score", is_num),
    "raw_lo": ("raw_lo", is_int),
    "raw_hi": ("raw_hi", is_int),
    "page": ("page", is_int),
    "frac": ("frac", _is_frac),
    "pdf_build": ("pdf_build", _is_text),
    "frac_build": ("frac_build", _is_text),
    "file_rel": ("file_rel", _is_text),
    "edited_at": ("edited_at", _is_text),
    "edited_by": ("edited_by", _is_signature),
}
# A region pin's page and frac are its place (Region), so its core lifts every other plain field.
REGION_CORE_SHAPES: Shapes = {key: shape for key, shape in CORE_SHAPES.items() if key not in ("page", "frac")}


@dataclass(frozen=True)
class OpenPin:
    """A pin nobody has closed: its stored done is false or missing. Only an open pin carries a claim.

    A pin reopened after a close keeps that close's done_at/closed_by among its fields - the history of an earlier
    close, not a close of this pin; claim fields without a claimed_by object are kept there too and are no claim.
    """

    state: ClassVar[StateName] = "open"
    core: PinCore
    claim: Claim | None
    fields: Record
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject a stored done that says closed, or a core or claim field held twice."""
        _check(self, self.fields, self._lifted())

    def _lifted(self) -> dict[str, Any]:
        """The core and the claim as stored fields."""
        return {**self.core.stored(), **_stored(self.claim, CLAIM_SHAPES)}

    @classmethod
    def from_record(cls, record: Record) -> OpenPin:
        """The open pin a stored record describes; ValueError if its done says it is closed."""
        core = PinCore.from_record(record)
        claim = _lift(record, CLAIM_SHAPES, Claim, required=("by",))
        lifted = {**core.stored(), **_stored(claim, CLAIM_SHAPES)}
        return cls(core, claim, _others(record, lifted), tuple(record))

    @property
    def record(self) -> dict[str, Any]:
        """The pin as stored: a new dict in stored field order, the core and the claim written back where they were."""
        return _render(self.fields, self.order, self._lifted())


@dataclass(frozen=True)
class ReviewPin:
    """Closed by an agent and waiting for a person to confirm it: done and review are both true. It has a close and
    no claim; a confirmation comes only with the move to done."""

    state: ClassVar[StateName] = "review"
    core: PinCore
    close: Close
    fields: Record
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject stored done/review that do not say awaiting review, or a core or close field held twice."""
        _check(self, self.fields, self._lifted())

    def _lifted(self) -> dict[str, Any]:
        """The core and the close as stored fields."""
        return {**self.core.stored(), **_stored(self.close, CLOSE_SHAPES)}

    @classmethod
    def from_record(cls, record: Record) -> ReviewPin:
        """The pin awaiting review a stored record describes; ValueError unless done and review are true."""
        core = PinCore.from_record(record)
        close = Close(**_taken(record, CLOSE_SHAPES))
        lifted = {**core.stored(), **_stored(close, CLOSE_SHAPES)}
        return cls(core, close, _others(record, lifted), tuple(record))

    @property
    def record(self) -> dict[str, Any]:
        """The pin as stored: a new dict in stored field order, the core and the close written back where they were."""
        return _render(self.fields, self.order, self._lifted())


@dataclass(frozen=True)
class DonePin:
    """Closed for good: done without review. It has a close, a confirmation when a person confirmed it out of review,
    and no claim. A legacy done record with no review field is done too."""

    state: ClassVar[StateName] = "done"
    core: PinCore
    close: Close
    confirmation: Confirmation | None
    fields: Record
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject stored done/review that do not say done, or a core, close or confirmation field held twice."""
        _check(self, self.fields, self._lifted())

    def _lifted(self) -> dict[str, Any]:
        """The core, the close and the confirmation as stored fields."""
        return {
            **self.core.stored(),
            **_stored(self.close, CLOSE_SHAPES),
            **_stored(self.confirmation, CONFIRMATION_SHAPES),
        }

    @classmethod
    def from_record(cls, record: Record) -> DonePin:
        """The done pin a stored record describes; ValueError unless done is set and review is not true. A
        confirmation is lifted only whole - confirmed_by an object and confirmed_at a string."""
        core = PinCore.from_record(record)
        close = Close(**_taken(record, CLOSE_SHAPES))
        confirmation = _lift(record, CONFIRMATION_SHAPES, Confirmation, required=("by", "at"))
        lifted = {**core.stored(), **_stored(close, CLOSE_SHAPES), **_stored(confirmation, CONFIRMATION_SHAPES)}
        return cls(core, close, confirmation, _others(record, lifted), tuple(record))

    @property
    def record(self) -> dict[str, Any]:
        """The pin as stored: a new dict in stored field order, the core, close and confirmation written back where
        they were."""
        return _render(self.fields, self.order, self._lifted())


Pin: TypeAlias = OpenPin | ReviewPin | DonePin


def state_of(record: Record) -> type[OpenPin] | type[ReviewPin] | type[DonePin]:
    """The state type a stored record is in - the one rule of a pin's state, never stored: not done is open; done
    with review true is awaiting review; any other done (a legacy done:true without review too) is done. Reads only
    done and review, so it is cheap enough for every pin of every read (limn.pins.view.pin_state)."""
    if not record.get("done"):
        return OpenPin
    if record.get("review") is True:
        return ReviewPin
    return DonePin


def parse_pin(record: Record) -> Pin:
    """The state type of a stored record, by the rule of state_of(), with that state's fields lifted. Never fails:
    any JSON object is some state, and whatever does not fit is kept as stored."""
    return state_of(record).from_record(record)


@dataclass(frozen=True)
class TrashedPin:
    """A deleted pin in the Trash (pins.dropped.jsonl): the pin as it was, and who dropped it when - restorable by id.

    dropped is lifted when dropped_at is a string (drop() always writes it with dropped_by, an object); a dropped_by
    that is not an object, or one without a dropped_at string, stays among the pin's kept fields as stored.
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
        dropped = _lift(record, DROPPED_SHAPES, Dropped, required=("at",))
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


def is_region_pin(record: object) -> bool:
    """Is this a pin on a view-only PDF document - no file, but a pdf path? Told purely by the record's shape: even if the
    current configuration no longer has that document, the record is not broken (treating it as broken would delete
    the pin on the next write)."""
    return (
        isinstance(record, dict)
        and record.get("file") is None
        and isinstance(record.get("pdf"), str)
        and bool(record["pdf"])
    )


@dataclass(frozen=True)
class PinNotFound:
    """No pin with this id is in the store; the API answers ok:false rather than an error."""

    pid: int

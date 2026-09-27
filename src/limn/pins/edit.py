"""What editing a pin and adding one write: the validated requests, the rules that refuse an edit, and the records.

Pure like the rest of limn.pins. The shell (server.py) parses the request body, reads what only the disk and the
clock know - where the pin's file is now, its lines and mtime, the next id, who a login is - and passes those in as
values. It also builds the notices (events.jsonl) from the record that comes back. An edit that must be refused is
a returned value in the annotation, never an exception (docs/handbook/code-style-roadmap.md R1, R3).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from posixpath import isabs
from typing import Any, Literal, TypeAlias, TypeGuard, get_args

from limn.pins.lifecycle import PinT, author, rev_after, signature, thread_message, with_entry
from limn.pins.model import Actor, DonePin, KindReq, LineSpan, OpenPin, Pin, Record, ReviewPin, is_kind_req
from limn.pins.shapes import is_finite_num, is_int

# The assignee value that hands a pin to the agent rather than to a person (docs/handbook/api.md §담당).
ASSIGNEE_AGENT = "agent"
# The headerless loopback agent's login (server.LOCAL_ACTOR). It is never a person, so never an assignee.
LOCAL_LOGIN = "local"
# A pin's note, in characters: the limit a new or replaced note must fit, and a note_append merged into it.
NOTE_MAX = 4000
# scope: which rung of the range ladder a line pin was placed at (limn.mapping.compute_levels: raw drag, paragraph,
# the innermost environment and up to two outer ones, or plain lines).
Scope: TypeAlias = Literal["raw", "para", "env", "env2", "env3", "lines"]
SCOPES: tuple[Scope, ...] = get_args(Scope)
# The region text a view-only PDF pin keeps as its quote - longer than a line pin's 60 characters, since the text is
# all an agent has to find the place by.
PDF_QUOTE_MAX = 160
# The location fields a line pin's re-placement (loc) replaces as a whole; fields it does not name are dropped.
LOC_FIELDS = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score", "frac", "scope", "quote")
# The fields a view-only PDF pin's new region may set; a region without a quote drops the old one.
REGION_PLACE_FIELDS = ("page", "frac", "quote", "pdf_build")


def _place_record(items: tuple[tuple[str, object], ...]) -> Record:
    """Rebuild ordered JSON fields, exposing a new list for a frozen place's fractional coordinates."""
    return {key: list(value) if key == "frac" and isinstance(value, tuple) else value for key, value in items}


def _place_items(fields: Record) -> tuple[tuple[str, object], ...]:
    """Freeze the known nested JSON list as well as a place's outer record while retaining its field order."""
    return tuple(
        (key, tuple(value) if key == "frac" and isinstance(value, list) else value) for key, value in fields.items()
    )


def is_scope(v: object) -> TypeGuard[Scope]:
    """Is v one of SCOPES? The check the add and edit parsers share."""
    return v in SCOPES


@dataclass(frozen=True, init=False)
class LinePlace:
    """A line pin's location with required local fields; the boundary also checks file existence and line count.

    named is the set of fields the request itself sent. An edit keeps the pin's page and frac when the request did
    not name them, and forgets the legacy frac_build only when it re-placed frac. The record snapshot cannot be
    changed through the caller's dict or the fields property after construction.
    """

    _items: tuple[tuple[str, object], ...]
    named: frozenset[str]
    file: str
    lo: int
    hi: int

    def __init__(self, fields: Record, named: frozenset[str]) -> None:
        """Keep the field order and reject a place that would fail the service's required field reads."""
        if not isinstance(fields, dict):
            raise ValueError("line place fields must be a record")
        if not fields.keys() <= set(LOC_FIELDS + ("pdf_build",)):
            raise ValueError("line place contains fields outside its location")
        if "frac" in named and "frac" not in fields:
            raise ValueError("a named frac requires replacement coordinates")
        file, name, lo, hi, page = (fields.get(key) for key in ("file", "name", "lo", "hi", "page"))
        if not (
            isinstance(file, str)
            and isabs(file)
            and isinstance(name, str)
            and bool(name)
            and is_int(lo)
            and is_int(hi)
            and 1 <= lo <= hi
            and is_int(page)
            and page >= 1
        ):
            raise ValueError("line place requires an absolute file, name, ordered positive lines and page")
        for key in ("raw_lo", "raw_hi"):
            if key in fields and not is_int(fields[key]):
                raise ValueError(f"line place {key} must be an integer")
        if "kind" in fields and (not isinstance(fields["kind"], str) or len(fields["kind"]) > 80):
            raise ValueError("line place kind must be a short string")
        if "via" in fields and fields["via"] not in ("synctex", "text"):
            raise ValueError("line place via must name a location method")
        if "score" in fields and not is_finite_num(fields["score"]):
            raise ValueError("line place score must be a finite number")
        if "frac" in fields:
            frac = fields["frac"]
            if not (isinstance(frac, list) and len(frac) == 4 and all(is_finite_num(x) for x in frac)):
                raise ValueError("line place frac must contain four finite numbers")
        if "scope" in fields and not is_scope(fields["scope"]):
            raise ValueError("line place scope must name a range level")
        if "quote" in fields and (not isinstance(fields["quote"], str) or len(fields["quote"]) > 60):
            raise ValueError("line place quote must be a short string")
        if "pdf_build" in fields and (not isinstance(fields["pdf_build"], str) or not fields["pdf_build"]):
            raise ValueError("line place pdf_build must be a nonempty string")
        object.__setattr__(self, "_items", _place_items(fields))
        object.__setattr__(self, "named", frozenset(named))
        object.__setattr__(self, "file", file)
        object.__setattr__(self, "lo", lo)
        object.__setattr__(self, "hi", hi)

    @property
    def fields(self) -> Record:
        """A fresh stored-shape record, preserving field order without exposing mutable request state."""
        return _place_record(self._items)


@dataclass(frozen=True, init=False)
class RegionPlace:
    """A view-only PDF pin's locally valid region; the boundary also checks the document's page count."""

    _items: tuple[tuple[str, object], ...]

    def __init__(self, fields: Record) -> None:
        """Reject missing PDF coordinates and keep an isolated snapshot of the ordered record fields."""
        if not isinstance(fields, dict):
            raise ValueError("region place fields must be a record")
        if not fields.keys() <= {"pdf", "name", "kind", "page", "frac", "quote", "pdf_build"}:
            raise ValueError("region place contains fields outside its location")
        pdf, name, page, frac = (fields.get(key) for key in ("pdf", "name", "page", "frac"))
        if not (
            isinstance(pdf, str)
            and isabs(pdf)
            and isinstance(name, str)
            and bool(name)
            and is_int(page)
            and page >= 1
            and fields.get("kind") == "region"
            and isinstance(frac, list)
            and len(frac) == 4
            and all(is_finite_num(value) for value in frac)
        ):
            raise ValueError("region place requires an absolute PDF, name, page and four finite coordinates")
        x, y, w, h = frac
        eps = 1e-6
        if not (
            0 <= x <= 1
            and 0 <= y <= 1
            and 0 < w <= 1 + eps
            and 0 < h <= 1 + eps
            and x + w <= 1 + eps
            and y + h <= 1 + eps
        ):
            raise ValueError("region place must have positive area inside the page")
        if "quote" in fields and (not isinstance(fields["quote"], str) or len(fields["quote"]) > PDF_QUOTE_MAX):
            raise ValueError("region place quote must be a short string")
        if "pdf_build" in fields and (not isinstance(fields["pdf_build"], str) or not fields["pdf_build"]):
            raise ValueError("region place pdf_build must be a nonempty string")
        object.__setattr__(self, "_items", _place_items(fields))

    @property
    def fields(self) -> Record:
        """A fresh stored-shape record, preserving field order without exposing mutable request state."""
        return _place_record(self._items)


Place: TypeAlias = LinePlace | RegionPlace


@dataclass(frozen=True)
class EditRequest:
    """A validated edit: each field is None when the request did not send it (hints are empty then).

    note is the replacement note ("" for a JSON null); note_append is text to add under the note. place re-places the
    pin; lo/hi move a line pin's range without re-placing it. kind_req and assignee are note-level and may change on
    a closed pin. base_rev is the rev the editor loaded; only a note_append may leave it out.
    """

    base_rev: int | None = None
    note: str | None = None
    note_append: str | None = None
    place: Place | None = None
    lo: int | None = None
    hi: int | None = None
    scope: Scope | None = None
    kind: str | None = None
    kind_req: KindReq | None = None
    assignee: str | None = None
    hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject locally invalid edit fields even when a caller bypasses the HTTP parser."""
        if self.base_rev is not None and not is_int(self.base_rev):
            raise ValueError("base_rev must be an integer")
        if self.note is not None and (not isinstance(self.note, str) or len(self.note) > NOTE_MAX):
            raise ValueError("note must be a short string")
        if self.note_append is not None and (
            not isinstance(self.note_append, str) or not self.note_append.strip() or len(self.note_append) > 2000
        ):
            raise ValueError("note_append must be a short nonblank string")
        if self.place is not None and not isinstance(self.place, (LinePlace, RegionPlace)):
            raise ValueError("place must be a pin location")
        if any(value is not None and not is_int(value) for value in (self.lo, self.hi)):
            raise ValueError("lo and hi must be integers")
        if self.scope is not None and not is_scope(self.scope):
            raise ValueError("scope must name a range level")
        if self.kind is not None and (not isinstance(self.kind, str) or len(self.kind) > 80):
            raise ValueError("kind must be a short string")
        if self.kind_req is not None and not is_kind_req(self.kind_req):
            raise ValueError("kind_req must name a pin kind")
        if self.assignee is not None and (not isinstance(self.assignee, str) or not self.assignee):
            raise ValueError("assignee must be a nonempty string")
        if not isinstance(self.hints, tuple) or not all(isinstance(hint, str) for hint in self.hints):
            raise ValueError("hints must be login strings")

    def reshapes(self) -> bool:
        """Does the edit change where the pin points or what it spans (place, lines, scope, kind)? A closed pin refuses that."""
        return (
            self.place is not None
            or self.lo is not None
            or self.hi is not None
            or self.scope is not None
            or self.kind is not None
        )

    def sets_lines(self) -> bool:
        """Does the edit move the range by lo/hi alone? Then the new lines must fit the pin's file, which the shell counts."""
        return self.place is None and (self.lo is not None or self.hi is not None)


@dataclass(frozen=True)
class ClosedPinReshaped:
    """A closed pin keeps where it points: only its note and note-level fields may change. The pin goes into the 409 body."""

    pin: ReviewPin | DonePin


@dataclass(frozen=True)
class StaleEdit:
    """base_rev is not the pin's rev: an agent closed it or line matching moved it after the editor loaded it."""

    pin: Pin


@dataclass(frozen=True)
class NoteTooLong:
    """Appending would make the note longer than the limit; length is the merged note's."""

    length: int
    limit: int


@dataclass(frozen=True)
class PinOutsideTree:
    """The pin's file cannot be placed inside the manuscript tree, so a new lo/hi cannot be checked; loc re-places it."""


@dataclass(frozen=True)
class RangeOutsideFile:
    """The new lo..hi does not fit in the pin's file, which has `lines` lines."""

    lines: int
    lo: int
    hi: int


EditRefusal: TypeAlias = ClosedPinReshaped | StaleEdit | NoteTooLong | PinOutsideTree | RangeOutsideFile


@dataclass(frozen=True)
class PinEdited:
    """The fact of an accepted edit: who and when, the note as it will read, and the location, range and fields it sets.

    note is None when the edit leaves the note alone (a note_append arrives here merged). lines is the lo/hi an edit
    without place writes; range_changed says whether the pin's lines moved (always for a line re-placement), which is
    when the shell re-reads the file for a new anchor.
    """

    by: Actor
    at: str
    note: str | None
    place: Place | None
    lines: tuple[int, int] | None
    range_changed: bool
    scope: Scope | None
    kind: str | None
    kind_req: KindReq | None
    assignee: str | None

    def span(self) -> tuple[int, int] | None:
        """The lines to re-anchor: the pin's new range when it changed, else None."""
        if not self.range_changed:
            return None
        if isinstance(self.place, LinePlace):
            return self.place.lo, self.place.hi
        return self.lines


@dataclass(frozen=True)
class Located:
    """Where a line pin's file is on this machine: its absolute path and its path relative to the manuscript root."""

    path: str
    rel: str


@dataclass(frozen=True)
class Anchoring:
    """A range's anchor captured from the file's current lines, and the file's mtime at that moment (synced_at)."""

    anchor: Record
    synced_at: float


def file_after(record: Record, request: EditRequest) -> Record:
    """The file fields the pin will carry after the edit - what the shell locates on disk before deciding.

    A line re-placement brings its own file; every other edit keeps the stored one. file_rel is never replaced here
    (it is not a location field), so the stored value goes along.
    """
    file = request.place.file if isinstance(request.place, LinePlace) else record.get("file")
    return {"file": file, "file_rel": record.get("file_rel")}


def decide_edit(
    pin: Pin, request: EditRequest, by: Actor, at: str, clock: str, line_count: int | None, note_max: int
) -> PinEdited | EditRefusal:
    """What an edit does to this pin, or why it is refused - checked in this order, before anything changes.

    A closed pin refuses a reshaping edit; a base_rev other than the pin's rev is stale; a note_append is merged
    under the note (or under the note this request replaces it with) after a "(추가 HH:MM)" stamp - clock is HH:MM -
    and refused if the result exceeds note_max. A lo/hi edit needs line_count, the line count of the pin's file
    (None when the file is outside the manuscript tree), and a pin placed on lines (core.place a LineSpan): the range
    must lie in 1..max(line_count, 1). The range counts as changed when it differs from the stored one or the pin had
    lost its place (core.stale).
    """
    if request.reshapes() and isinstance(pin, (ReviewPin, DonePin)):
        return ClosedPinReshaped(pin)
    if request.base_rev is not None and (pin.core.rev or 0) != request.base_rev:
        return StaleEdit(pin)
    note = request.note
    if request.note_append is not None:
        base = request.note if request.note is not None else pin.core.note or ""
        note = base + ("\n" if base else "") + "(추가 %s) " % clock + request.note_append
        if len(note) > note_max:
            return NoteTooLong(len(note), note_max)
    lines, changed = None, isinstance(request.place, LinePlace)
    if request.sets_lines():
        span = pin.core.place
        if line_count is None or not isinstance(span, LineSpan):
            return PinOutsideTree()
        lo = request.lo if request.lo is not None else span.lo
        hi = request.hi if request.hi is not None else span.hi
        if not 1 <= lo <= hi <= max(line_count, 1):
            return RangeOutsideFile(line_count, lo, hi)
        changed = (lo, hi) != (span.lo, span.hi) or bool(pin.core.stale)
        lines = (lo, hi)
    return PinEdited(
        by, at, note, request.place, lines, changed, request.scope, request.kind, request.kind_req, request.assignee
    )


def evolve_edit(
    pin: PinT,
    event: PinEdited,
    where: Located | None,
    anchoring: Anchoring | None,
    mentions: Sequence[str] | None,
    assignee_name: str | None,
) -> PinT:
    """Apply an edit; the pin keeps its state. Fields keep their order in the record (new ones go to the end).

    A region re-placement sets page, frac, quote (dropped if not sent) and pdf_build. A line re-placement replaces
    every location field, keeping page and frac the request did not name; kind defaults to the request's kind or
    "lines", scope comes from the request when the place has none. A lo/hi edit writes the range and, if it moved,
    forgets via/score (the range is no longer a matching result). scope and kind are set directly when nothing is
    re-placed. Then the facts the shell read: where the file is now (file, file_rel), and - given only when the
    range changed and the file is located - the new anchor and synced_at, which also clear stale/sync. Last come the
    note, kind_req, the note's @-tags (mentions, None when the note is untouched), a changed assignee with an
    ev=assign thread entry naming them (assignee_name is the person's display name), edited_at/by, and rev.
    """
    record = dict(pin.record)
    place = event.place
    if isinstance(place, RegionPlace):
        fields = place.fields
        for key in REGION_PLACE_FIELDS:
            if key in fields:
                record[key] = fields[key]
            elif key == "quote":
                record.pop("quote", None)
    elif isinstance(place, LinePlace):
        fields = place.fields
        keep = {key: record[key] for key in ("page", "frac") if key not in place.named and key in record}
        for key in LOC_FIELDS:
            record.pop(key, None)
        record.update(fields)
        record.update(keep)
        if "kind" not in fields:
            record["kind"] = event.kind if event.kind is not None else "lines"
        if event.scope is not None and "scope" not in fields:
            record["scope"] = event.scope
        if "frac" in place.named:  # build identity changes only when frac was re-placed
            record.pop("frac_build", None)  # legacy field name, superseded by pdf_build
    elif event.lines is not None:
        record["lo"], record["hi"] = event.lines
        if event.range_changed:
            record.pop("via", None)
            record.pop("score", None)
    if place is None:
        if event.scope is not None:
            record["scope"] = event.scope
        if event.kind is not None:
            record["kind"] = event.kind
    if where is not None:
        record["file"], record["file_rel"] = where.path, where.rel
    if anchoring is not None:
        record["anchor"] = anchoring.anchor
        record["synced_at"] = anchoring.synced_at
        record.pop("stale", None)
        record.pop("sync", None)
    if event.note is not None:
        record["note"] = event.note
    if event.kind_req is not None:
        record["kind_req"] = event.kind_req
    if mentions is not None:
        _set_mentions(record, mentions)
    if event.assignee is not None and pin.core.assignee != event.assignee:
        record["assignee"] = event.assignee
        text = assignment_text(event.assignee, assignee_name)
        record["thread"] = with_entry(
            pin.core.thread, thread_message(pin.core.thread, author(event.by), event.at, text, ev="assign")
        )
    record["edited_at"] = event.at
    record["edited_by"] = signature(event.by)
    record["rev"] = rev_after(pin.core.rev)
    return type(pin).from_record(record)


def assignment_text(assignee: str, name: str | None) -> str:
    """The ev=assign thread entry's text: "담당: 에이전트", or "담당: @<name>" for a person (their login without a name)."""
    return "담당: " + ("에이전트" if assignee == ASSIGNEE_AGENT else "@" + (name or assignee))


@dataclass(frozen=True)
class AddRequest:
    """A validated new pin: where it is, its note, and the optional kind_req, assignee and @-tag hints."""

    place: Place
    note: str
    kind_req: KindReq | None = None
    assignee: str | None = None
    hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Keep an internally constructed add's place and local fields in the same shapes as parsed input."""
        if not isinstance(self.place, (LinePlace, RegionPlace)):
            raise ValueError("place must be a pin location")
        if not isinstance(self.note, str) or len(self.note) > NOTE_MAX:
            raise ValueError("note must be a short string")
        if self.kind_req is not None and not is_kind_req(self.kind_req):
            raise ValueError("kind_req must name a pin kind")
        if self.assignee is not None and (not isinstance(self.assignee, str) or not self.assignee):
            raise ValueError("assignee must be a nonempty string")
        if not isinstance(self.hints, tuple) or not all(isinstance(hint, str) for hint in self.hints):
            raise ValueError("hints must be login strings")


def new_line_pin(
    place: LinePlace,
    request: AddRequest,
    pid: int,
    at: str,
    author_record: Record,
    mentions: Sequence[str],
    anchoring: Anchoring,
    pdf_build: str,
    doc: str,
    where: Located | None,
) -> OpenPin:
    """A new line pin's record, fields in the order the store has always written them.

    The location comes first (kind defaults to "lines"), then note, at, id (pid, allocated by the shell), author (the
    request's actor as given), kind_req, the note's @-tags, assignee, the anchor and synced_at the shell captured,
    pdf_build (the one the viewer sent, else the current build), doc, rev 0, and last where the file is now (ADR-0006).
    """
    record = dict(place.fields)
    record.setdefault("kind", "lines")
    record.update(note=request.note, at=at, id=pid, author=dict(author_record))
    if request.kind_req:
        record["kind_req"] = request.kind_req
    _set_mentions(record, mentions)
    if request.assignee is not None:
        record["assignee"] = request.assignee
    record["anchor"] = anchoring.anchor
    record["synced_at"] = anchoring.synced_at
    record.setdefault("pdf_build", pdf_build)
    record["doc"] = doc
    record["rev"] = 0
    if where is not None:
        record["file"], record["file_rel"] = where.path, where.rel
    return OpenPin.from_record(record)


def new_region_pin(
    place: RegionPlace,
    request: AddRequest,
    pid: int,
    at: str,
    author_record: Record,
    mentions: Sequence[str],
    pdf_build: str,
    doc: str,
) -> OpenPin:
    """A new view-only PDF pin's record: the region, note, at, id, author, kind_req, pdf_build, doc, rev 0, then the
    note's @-tags and the assignee - the order this kind of pin has always been written in. No lines, no anchor."""
    record = dict(place.fields)
    record.update(note=request.note, at=at, id=pid, author=dict(author_record))
    if request.kind_req:
        record["kind_req"] = request.kind_req
    record.setdefault("pdf_build", pdf_build)
    record["doc"] = doc
    record["rev"] = 0
    _set_mentions(record, mentions)
    if request.assignee is not None:
        record["assignee"] = request.assignee
    return OpenPin.from_record(record)


def _set_mentions(record: dict[str, Any], mentions: Sequence[str]) -> None:
    """Store the note's resolved @-tags as mentions, or drop the field when there are none."""
    if mentions:
        record["mentions"] = list(mentions)
    else:
        record.pop("mentions", None)

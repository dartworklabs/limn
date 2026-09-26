"""What editing a pin and adding one write: the validated requests, the rules that refuse an edit, and the records.

Pure like the rest of limn.pins. The shell (server.py) parses the request body, reads what only the disk and the
clock know - where the pin's file is now, its lines and mtime, the next id, who a login is - and passes those in as
values. It also builds the notices (events.jsonl) from the record that comes back. An edit that must be refused is
a returned value in the annotation, never an exception (docs/handbook/code-style-roadmap.md R1, R3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

from limn.pins.lifecycle import PinT, author, next_rev, signature, thread_message, thread_of
from limn.pins.model import Actor, DonePin, OpenPin, Pin, Record, ReviewPin

# The assignee value that hands a pin to the agent rather than to a person (docs/handbook/api.md §담당).
ASSIGNEE_AGENT = "agent"
# The headerless loopback agent's login (server.LOCAL_ACTOR). It is never a person, so never an assignee.
LOCAL_LOGIN = "local"
# A pin's note, in characters: the limit a new or replaced note must fit, and a note_append merged into it.
NOTE_MAX = 4000
# kind_req: what a pin asks for - a fix (the default; every legacy pin is one) or an answer (docs/handbook/api.md §스레드).
KIND_REQS = ("fix", "question")
# The region text a view-only PDF pin keeps as its quote - longer than a line pin's 60 characters, since the text is
# all an agent has to find the place by.
PDF_QUOTE_MAX = 160
# The location fields a line pin's re-placement (loc) replaces as a whole; fields it does not name are dropped.
LOC_FIELDS = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score", "frac", "scope", "quote")
# The fields a view-only PDF pin's new region may set; a region without a quote drops the old one.
REGION_PLACE_FIELDS = ("page", "frac", "quote", "pdf_build")


@dataclass(frozen=True)
class LinePlace:
    """A line pin's location, validated against its file (file, name, lo, hi, page and the optional fields).

    named is the set of fields the request itself sent. An edit keeps the pin's page and frac when the request did
    not name them, and forgets the legacy frac_build only when it re-placed frac.
    """

    fields: Record
    named: frozenset[str]


@dataclass(frozen=True)
class RegionPlace:
    """A view-only PDF pin's region, validated against the document's pages: page, frac, optional quote and pdf_build."""

    fields: Record


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
    scope: str | None = None
    kind: str | None = None
    kind_req: str | None = None
    assignee: str | None = None
    hints: tuple[str, ...] = ()

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
    scope: str | None
    kind: str | None
    kind_req: str | None
    assignee: str | None

    def span(self) -> tuple[int, int] | None:
        """The lines to re-anchor: the pin's new range when it changed, else None."""
        if not self.range_changed:
            return None
        if isinstance(self.place, LinePlace):
            return self.place.fields["lo"], self.place.fields["hi"]
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
    file = request.place.fields["file"] if isinstance(request.place, LinePlace) else record.get("file")
    return {"file": file, "file_rel": record.get("file_rel")}


def decide_edit(
    pin: Pin, request: EditRequest, by: Actor, at: str, clock: str, line_count: int | None, note_max: int
) -> PinEdited | EditRefusal:
    """What an edit does to this pin, or why it is refused - checked in this order, before anything changes.

    A closed pin refuses a reshaping edit; a base_rev other than the pin's rev is stale; a note_append is merged
    under the note (or under the note this request replaces it with) after a "(추가 HH:MM)" stamp - clock is HH:MM -
    and refused if the result exceeds note_max. A lo/hi edit needs line_count, the line count of the pin's file
    (None when the file is outside the manuscript tree): the range must lie in 1..max(line_count, 1). The range counts
    as changed when it differs from the stored one or the pin had lost its place (stale).
    """
    if request.reshapes() and isinstance(pin, (ReviewPin, DonePin)):
        return ClosedPinReshaped(pin)
    if request.base_rev is not None and int(pin.record.get("rev") or 0) != request.base_rev:
        return StaleEdit(pin)
    note = request.note
    if request.note_append is not None:
        base = request.note if request.note is not None else str(pin.record.get("note") or "")
        note = base + ("\n" if base else "") + "(추가 %s) " % clock + request.note_append
        if len(note) > note_max:
            return NoteTooLong(len(note), note_max)
    lines, changed = None, isinstance(request.place, LinePlace)
    if request.sets_lines():
        lo = request.lo if request.lo is not None else pin.record["lo"]
        hi = request.hi if request.hi is not None else pin.record["hi"]
        if line_count is None:
            return PinOutsideTree()
        if not 1 <= lo <= hi <= max(line_count, 1):
            return RangeOutsideFile(line_count, lo, hi)
        changed = (lo, hi) != (pin.record["lo"], pin.record["hi"]) or bool(pin.record.get("stale"))
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
        for key in REGION_PLACE_FIELDS:
            if key in place.fields:
                record[key] = place.fields[key]
            elif key == "quote":
                record.pop("quote", None)
    elif isinstance(place, LinePlace):
        keep = {key: record[key] for key in ("page", "frac") if key not in place.named and key in record}
        for key in LOC_FIELDS:
            record.pop(key, None)
        record.update(place.fields)
        record.update(keep)
        if "kind" not in place.fields:
            record["kind"] = event.kind if event.kind is not None else "lines"
        if event.scope is not None and "scope" not in place.fields:
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
    if event.assignee is not None and record.get("assignee") != event.assignee:
        record["assignee"] = event.assignee
        record["thread"] = [
            *thread_of(pin.record),
            thread_message(
                pin.record.get("thread"),
                author(event.by),
                event.at,
                assignment_text(event.assignee, assignee_name),
                ev="assign",
            ),
        ]
    record["edited_at"] = event.at
    record["edited_by"] = signature(event.by)
    record["rev"] = next_rev(pin.record)
    return type(pin).from_record(record)


def assignment_text(assignee: str, name: str | None) -> str:
    """The ev=assign thread entry's text: "담당: 에이전트", or "담당: @<name>" for a person (their login without a name)."""
    return "담당: " + ("에이전트" if assignee == ASSIGNEE_AGENT else "@" + (name or assignee))


@dataclass(frozen=True)
class AddRequest:
    """A validated new pin: where it is, its note, and the optional kind_req, assignee and @-tag hints."""

    place: Place
    note: str
    kind_req: str | None = None
    assignee: str | None = None
    hints: tuple[str, ...] = ()


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

"""Adding a pin and editing one in place (docs/handbook/api.md §핀 만들기, §핀 고치기).

The handler parses the body (limn.web.parse.parse_add, parse_edit and parse_edit_place); these shells read what only
the disk and the clock know under the pin lock, and leave the rules and the record to limn.pins.edit. Each returns an
outcome value that the HTTP layer answers (limn.web.answers.add_answer, edit_answer).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from limn import build
from limn.documents import Doc
from limn.files import tex_lines
from limn.locate import PinLocation
from limn.mapping import anchor_of
from limn.pins.edit import (
    ASSIGNEE_AGENT, NOTE_MAX, AddRequest, Anchoring, EditRefusal, EditRequest, LinePlace, Located, PinEdited,
    RegionPlace, decide_edit, evolve_edit, file_after, new_line_pin, new_region_pin,
)
from limn.pins.model import DonePin, OpenPin, Pin, PinNotFound, ReviewPin, parse_pin
from limn.service.context import Event, PinContext, Row, typed_actor
from limn.store import find_pin


def located(loc: PinLocation | None) -> Located | None:
    """A pin location found on disk (PinContext.locate) as the value limn.pins.edit records: absolute path and rel."""
    return None if loc is None else Located(str(loc.path), loc.rel)


def add_pin(ctx: PinContext, D: Doc, request: AddRequest, actor: Mapping[str, Any]) -> OpenPin:
    """Saves a new pin in document D from a parsed POST /api/pin body (limn.web.parse.parse_add) -> the new open pin. A
    LaTeX document gets a line pin with its anchor, the author and - since 0.3.2 (ADR-0006) - file_rel next to the
    absolute file; a view-only document gets a region pin. Queues mention/assigned notices and emits them after the
    write."""
    match request.place:
        case LinePlace() as place:
            return _add_line_pin(ctx, place, request, actor, D)
        case RegionPlace() as place:
            return _add_region_pin(ctx, place, request, actor, D)


def _add_line_pin(ctx: PinContext, place: LinePlace, request: AddRequest, actor: Mapping[str, Any],
                  D: Doc) -> OpenPin:
    """Append a new line pin to document D under the pin lock and emit its notices.

    The file's lines are read before the lock (as always); under it the shell takes the time, the next id (pins.seq),
    the note's @-tags, the anchor over those lines with the file's mtime, the current build and where the file is now,
    and limn.pins.edit.new_line_pin() builds the record. The notices are made from the finished record, so they name
    the pin's own document D.
    """
    f = Path(place.fields["file"])
    lines = tex_lines(f)
    evs: list[Event | None] = []

    def fn(rows: list[Row]) -> tuple[OpenPin, bool]:
        """The transact() step: builds the pin, appends it and queues its notices -> (pin, True)."""
        at = ctx.now()
        pid = ctx.store.next_id(rows)
        tags = ctx.note_tags(request.note, "", rows, request.hints, actor, pid)
        anchoring = Anchoring(anchor_of(lines, place.fields["lo"], place.fields["hi"]),
                              f.stat().st_mtime if f.exists() else 0)
        # Pins down which build's layout coordinates frac belongs to, by build identity (§Position estimation): the
        # viewer echoes pdf_build from the pick response; a call without it (agent curl) takes the current build.
        pin = new_line_pin(place, request, pid, at, actor, tags.mentions, anchoring, build.cur_pages(D).name, D.key,
                           located(ctx.locate({"file": place.fields["file"]})))
        rows.append(dict(pin.record))
        evs.append(ctx.make_event("mention", pin.record, actor, tags.notify, text=request.note))
        if request.assignee is not None and request.assignee != ASSIGNEE_AGENT:
            evs.append(ctx.make_event("assigned", pin.record, actor, [request.assignee], text=request.note))
        return pin, True
    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def _add_region_pin(ctx: PinContext, place: RegionPlace, request: AddRequest, actor: Mapping[str, Any],
                    D: Doc) -> OpenPin:
    """Append a new pin on view-only document D under the pin lock and emit its notices: {doc, pdf, name, page, frac,
    kind: 'region', quote?, note, pdf_build}, built by limn.pins.edit.new_region_pin(). No lines, no anchor."""
    evs: list[Event | None] = []

    def fn(rows: list[Row]) -> tuple[OpenPin, bool]:
        """The transact() step: builds the pin, appends it and queues its notices -> (pin, True)."""
        at = ctx.now()
        pid = ctx.store.next_id(rows)
        tags = ctx.note_tags(request.note, "", rows, request.hints, actor, pid)
        pin = new_region_pin(place, request, pid, at, actor, tags.mentions, build.cur_pages(D).name, D.key)
        rows.append(dict(pin.record))
        evs.append(ctx.make_event("mention", pin.record, actor, tags.notify, text=request.note))
        if request.assignee is not None and request.assignee != ASSIGNEE_AGENT:
            evs.append(ctx.make_event("assigned", pin.record, actor, [request.assignee], text=request.note))
        return pin, True
    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def edit_pin(ctx: PinContext, pid: int, request: EditRequest, actor: Mapping[str, Any],
             region: bool = False) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
    """Edits pin pid's note, range, location and note-level fields in place; id/at/done never change.

    request is the parsed body with its loc already placed against the pin's own document (limn.web.parse.parse_edit
    and parse_edit_place, with region and the document from server.edit_scope()); region says the pin is a view-only
    one, whose file is never located. The 'HH:MM' an appended note is stamped with is read before the lock. Under the
    pin lock the shell reads where the pin's file will be and - for a lo/hi edit - its line count, and
    limn.pins.edit.decide_edit() refuses or accepts: a closed pin cannot be reshaped, a stale base_rev is a conflict
    (so a pin the agent closed, or one line matching moved, is never silently overwritten with stale lo/hi), a merged
    note_append must fit NOTE_MAX, lo/hi must fit the file. Refusals write nothing of their own. An accepted edit gets
    a new anchor when its range changed, the note's @-tags, edited_at/by and rev (evolve_edit); mention/assigned
    notices are emitted after the write.
    """
    clock = ctx.hm() if request.note_append is not None else ""
    evs: list[Event | None] = []

    def fn(rows: list[Row]) -> tuple[OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound, bool]:
        """The transact() step: decide the edit on pin pid and, if accepted, write it in place and queue its notices."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        pin = parse_pin(r)
        where = None if region else ctx.locate(file_after(r, request))   # ADR-0006: an edit records where the file is now
        count = len(tex_lines(where.path)) if where is not None and request.sets_lines() else None
        event = decide_edit(pin, request, typed_actor(actor), ctx.now(), clock, count, NOTE_MAX)
        if not isinstance(event, PinEdited):
            return event, False
        span = event.span()
        anchoring = None
        if span is not None and where is not None:
            f = where.path
            anchoring = Anchoring(anchor_of(tex_lines(f), *span), f.stat().st_mtime if f.exists() else 0)
        tags = None if event.note is None else ctx.note_tags(event.note, str(r.get("note") or ""), rows,
                                                             request.hints, actor, pid)
        assigns = request.assignee not in (None, ASSIGNEE_AGENT) and r.get("assignee") != request.assignee
        edited = _with_edit(pin, event, located(where), anchoring, None if tags is None else tags.mentions,
                            ctx.person_name(request.assignee) if assigns and request.assignee is not None else None)
        r.clear()
        r.update(edited.record)
        if tags is not None:
            evs.append(ctx.make_event("mention", r, actor, tags.notify, text=r.get("note")))
        if assigns:
            evs.append(ctx.make_event("assigned", r, actor, [request.assignee], text=r.get("note")))
        return edited, True
    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def _with_edit(pin: Pin, event: PinEdited, where: Located | None, anchoring: Anchoring | None,
               mentions: Sequence[str] | None, assignee_name: str | None) -> Pin:
    """evolve_edit() on a pin of any state: an edit keeps the state, so each state goes in as its own type."""
    match pin:
        case OpenPin():
            return evolve_edit(pin, event, where, anchoring, mentions, assignee_name)
        case ReviewPin():
            return evolve_edit(pin, event, where, anchoring, mentions, assignee_name)
        case DonePin():
            return evolve_edit(pin, event, where, anchoring, mentions, assignee_name)

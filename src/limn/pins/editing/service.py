"""Adding a pin and editing one in place (docs/handbook/api.md §핀 만들기와 상태 바꾸기, §핀 수정).

The handler parses the body (limn.pins.editing.input); these shells read what only
the disk and the clock know under the pin lock, and leave the rules and the record to limn.pins.editing.rules. Each returns an
outcome value that the HTTP layer answers (limn.pins.editing.http).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from limn.pins.context import Event, PinContext, load_pin, typed_actor
from limn.pins.editing.rules import (
    AddRefusal,
    AddRequest,
    Anchoring,
    EditRefusal,
    EditRequest,
    LinePlace,
    Located,
    PinEdited,
    RegionPlace,
    SuggestFacts,
    VerdictFacts,
    VerdictRefusal,
    decide_edit,
    decide_new_suggestion,
    decide_new_verdict,
    evolve_edit,
    file_after,
    new_line_pin,
    new_region_pin,
)
from limn.pins.editing.values import ASSIGNEE_AGENT, NOTE_MAX
from limn.pins.location.lookup import PinLocation
from limn.pins.location.mapping import anchor_of, comment_marker
from limn.pins.model import DonePin, OpenPin, Pin, PinNotFound, Record, Region, ReviewPin
from limn.pins.store import pin_index
from limn.pins.suggestion import Suggestion
from limn.pins.verdict import verdict_of, whole_figure
from limn.platform.files import tex_lines
from limn.runtime.documents import Doc, doc_by_key, document_authority_target
from limn.security.access import PostAuthority, require_authority


def located(loc: PinLocation | None) -> Located | None:
    """A pin location found on disk (PinContext.locate) as the value limn.pins.editing.rules records: absolute path and rel."""
    return None if loc is None else Located(str(loc.path), loc.rel)


def add_pin(ctx: PinContext, D: Doc, request: AddRequest, actor: PostAuthority) -> OpenPin | AddRefusal:
    """Saves a new pin in document D from a parsed POST /api/pin body (limn.pins.editing.input.parse_add) -> the new open pin. A
    LaTeX document gets a line pin with its anchor (which skips the comment lines of the file's kind,
    comment_marker), the author and - since 0.3.2 (ADR-0006) - file_rel next to the absolute file; a view-only
    document gets a region pin, and so does a figure document for a region pick (a drag that found no lines). Queues
    mention/assigned notices and emits them after the write.

    A request with a suggested edit is decided first (limn.pins.editing.rules.decide_new_suggestion): only a line pin
    of a LaTeX document (D.builds_from_source) takes one, within its limits, and its base must be what the pin's lines
    read in the same snapshot the anchor is taken from. A refusal is returned and nothing is written - no id is
    allocated and no transaction runs.

    A request with a verdict is decided inside the transaction, before an id is allocated, against the keys D declares
    at that moment (ctx.verdict_keys), whether the principal may make one (Principal.authors_verdicts) and - for a
    figure document's pin that names its page's whole figure (el.path == [el.id]) - whether the map of the pin's build
    (the pdf_build it sent, else the build on screen) has that element as the root of the pin's page
    (ctx.builds.page_root): limn.pins.editing.rules.decide_new_verdict. Its suggestion, if it sent one, is never
    decided - the verdict decision refuses every such request - so the verdict's refusals come in their own order. A
    refusal writes nothing of its own (a re-sync of the stored pins may still be written, as for any transaction)."""
    require_authority(actor, ctx.authority_scope, "add", document_authority_target(D))
    place = request.place
    # Manuscript text is read before taking the pin lock, as it was for line pins before this shared transaction.
    location = ctx.locate({"file": place.file}) if isinstance(place, LinePlace) else None
    lines, mtime = location.source.snapshot() if location is not None else ([], 0.0)
    if request.suggest is not None and request.verdict is None:
        decided = decide_new_suggestion(request.suggest, place, D.builds_from_source, lines)
        if not isinstance(decided, Suggestion):
            return decided
    author = actor.principal.authors_verdicts()
    evs: list[Event | None] = []

    def fn(pins: list[Pin]) -> tuple[OpenPin | VerdictRefusal, bool]:
        """Decide the verdict, if one was asked for, then allocate one id, build either location kind, and queue
        notices in the same transaction."""
        verdict = None
        if request.verdict is not None:
            facts = VerdictFacts(author, ctx.verdict_keys(D), _page_target_holds(ctx, D, place))
            judged = decide_new_verdict(request.verdict, request, facts)
            if not isinstance(judged, str):
                return judged, False
            verdict = judged
        at = ctx.now()
        pid = ctx.store.next_id(pins)
        tags = ctx.note_tags(request.note, "", pins, request.hints, actor, pid)
        match place:
            case LinePlace():
                assert lines is not None  # read before the lock for every LinePlace
                anchoring = Anchoring(anchor_of(lines, place.lo, place.hi, comment_marker(place.file)), mtime)
                # The viewer echoes pdf_build from pick; an agent request without it uses the current build.
                pin = new_line_pin(
                    place,
                    request,
                    pid,
                    at,
                    actor,
                    tags.mentions,
                    anchoring,
                    ctx.builds.heading(D).build,
                    D.key,
                    located(ctx.locate({"file": place.file})),
                    verdict,
                )
            case RegionPlace():
                pin = new_region_pin(
                    place, request, pid, at, actor, tags.mentions, ctx.builds.heading(D).build, D.key, verdict
                )
        pins.append(pin)
        evs.append(ctx.make_event("mention", pin.record, actor, tags.notify, text=request.note))
        if request.assignee is not None and request.assignee != ASSIGNEE_AGENT:
            evs.append(ctx.make_event("assigned", pin.record, actor, [request.assignee], text=request.note))
        return pin, True

    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def _page_target_holds(ctx: PinContext, D: Doc, place: LinePlace | RegionPlace) -> bool:
    """Whether a new pin's page target holds (limn.pins.editing.rules.VerdictFacts.page_target_holds): False only for
    a figure document's pin whose el names its page's whole figure (limn.pins.verdict.whole_figure) when the map of
    the pin's build - the pdf_build the request sent, else the build on screen - does not have that element as the
    root of the pin's page. Asks the build owner (ctx.builds.page_root) only then; reads no file itself."""
    fields = place.fields
    figure = whole_figure(fields) if D.has_element_map else None
    if figure is None:
        return True
    build = fields.get("pdf_build") or ctx.builds.heading(D).build
    return ctx.builds.page_root(D, build, fields["page"], figure)


def edit_pin(
    ctx: PinContext, pid: int, request: EditRequest, actor: PostAuthority, region: bool = False, latex: bool = False
) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
    """Edits pin pid's note, range, location and note-level fields in place; id/at/done never change.

    request is the parsed body with its loc already placed against the pin's own document (limn.pins.editing.input.parse_edit
    and parse_edit_place, with the EditTarget from EditScope - a verdict pin's loc is left unread); region says the
    pin is a region pin - a view-only document's, or a figure document's region pick - whose file is never located. The 'HH:MM' an appended note
    is stamped with is read before the lock. Under the pin lock the shell reads where the pin's file will be and - for a
    lo/hi edit - its line count, and limn.pins.editing.rules.decide_edit() refuses or accepts: a closed pin cannot be
    reshaped, a stale base_rev is a conflict (so a pin the agent closed, or one line matching moved, is never silently
    overwritten with stale lo/hi), a merged note_append must fit NOTE_MAX, lo/hi must fit the file. Refusals write
    nothing of their own. An accepted edit gets a new anchor when its range changed (which skips the comment lines of
    the file's kind, comment_marker), the note's @-tags, edited_at/by and rev (evolve_edit); mention/assigned notices
    are emitted after the write. An edit that sets a suggested edit also has the pin's file read under the lock - the
    file the pin will point at - so its base is compared with the lines it replaces after this edit; latex says the
    pin's document is a LaTeX one (Doc.builds_from_source), the only kind whose line pins take a suggestion.
    """
    require_authority(actor, ctx.authority_scope, "edit", pid)
    clock = ctx.hm() if request.note_append is not None else ""
    evs: list[Event | None] = []

    def fn(pins: list[Pin]) -> tuple[OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound, bool]:
        """The transact() step: decide the edit on pin pid and, if accepted, put the edited pin in its place and queue
        its notices."""
        found = load_pin(pins, pid)
        if isinstance(found, PinNotFound):
            return found, False
        i, pin = found
        # ADR-0006: an edit records where the file is now
        where = None if region else ctx.locate(file_after(pin.record, request))
        reads = request.sets_lines() or request.sets_suggestion()  # one read serves both checks
        source = tex_lines(where.source) if where is not None and reads else None
        count = len(source) if source is not None and request.sets_lines() else None
        facts = SuggestFacts(latex, None if source is None else tuple(source)) if request.sets_suggestion() else None
        event = decide_edit(pin, request, typed_actor(actor), ctx.now(), clock, count, NOTE_MAX, facts)
        if not isinstance(event, PinEdited):
            return event, False
        span = event.span()
        anchoring = None
        if span is not None and where is not None:
            lines, mtime = where.source.snapshot()
            anchoring = Anchoring(anchor_of(lines, *span, comment_marker(str(where.path))), mtime)
        tags = (
            None
            if event.note is None
            else ctx.note_tags(event.note, pin.core.note or "", pins, request.hints, actor, pid)
        )
        assigns = request.assignee not in (None, ASSIGNEE_AGENT) and pin.core.assignee != request.assignee
        edited = _with_edit(
            pin,
            event,
            located(where),
            anchoring,
            None if tags is None else tags.mentions,
            ctx.person_name(request.assignee) if assigns and request.assignee is not None else None,
        )
        pins[i] = edited
        rec = edited.record
        if tags is not None:
            evs.append(ctx.make_event("mention", rec, actor, tags.notify, text=rec.get("note")))
        if assigns:
            evs.append(ctx.make_event("assigned", rec, actor, [request.assignee], text=rec.get("note")))
        return edited, True

    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def _with_edit(
    pin: Pin,
    event: PinEdited,
    where: Located | None,
    anchoring: Anchoring | None,
    mentions: Sequence[str] | None,
    assignee_name: str | None,
) -> Pin:
    """evolve_edit() on a pin of any state: an edit keeps the state, so each state goes in as its own type."""
    match pin:
        case OpenPin():
            return evolve_edit(pin, event, where, anchoring, mentions, assignee_name)
        case ReviewPin():
            return evolve_edit(pin, event, where, anchoring, mentions, assignee_name)
        case DonePin():
            return evolve_edit(pin, event, where, anchoring, mentions, assignee_name)


@dataclass(frozen=True)
class EditTarget:
    """What an edit's location is parsed against, read before the pin lock (EditScope): whether the pin is a region
    pin (a view-only document's, or a figure document's region pick - it has no lines), whether it carries a verdict
    (limn.pins.verdict.verdict_of - then no loc is read, limn.pins.editing.input.parse_edit_place) and the document
    it belongs to. A verdict never leaves a pin, and the editing rules check the pin again under the lock."""

    region: bool
    verdict: bool
    document: Doc


@dataclass(frozen=True)
class EditScope:
    """Read a pin's region kind, verdict and owning document before parsing an edit's location."""

    read_pins: Callable[[], tuple[list[Pin], list[int]]]
    docs: Callable[[], Sequence[Doc]]
    pin_doc_key: Callable[[Record], str]

    def __call__(self, pid: int) -> EditTarget:
        """The pin's EditTarget. An id that is not among the live pins reads as a line pin without a verdict in the
        first document; the pin transaction answers a pin that is still missing as not found."""
        pins, _ = self.read_pins()
        docs = self.docs()
        i = pin_index(pins, pid)
        if i is None:
            return EditTarget(False, False, docs[0])
        pin = pins[i]
        return EditTarget(
            isinstance(pin.core.place, Region),
            verdict_of(pin.record) is not None,
            doc_by_key(docs, self.pin_doc_key(pin.record)) or docs[0],
        )


@dataclass(frozen=True)
class PinEditing:
    """Pin creation and editing bound to one application's context factory."""

    context: Callable[[], PinContext]

    def add_pin(self, D: Doc, request: AddRequest, actor: PostAuthority) -> OpenPin | AddRefusal:
        """Create one pin and emit notices after its transaction, or return why its suggested edit is refused."""
        ctx = self.context()
        require_authority(actor, ctx.authority_scope, "add", document_authority_target(D))
        return add_pin(ctx, D, request, actor)

    def edit_pin(
        self, pid: int, request: EditRequest, actor: PostAuthority, region: bool = False, latex: bool = False
    ) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
        """Edit one pin under the store lock and emit accepted notices; latex: the pin's document is a LaTeX one."""
        ctx = self.context()
        require_authority(actor, ctx.authority_scope, "edit", pid)
        return edit_pin(ctx, pid, request, actor, region, latex)

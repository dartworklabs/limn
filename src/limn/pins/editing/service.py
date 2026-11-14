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
    AskedVerdict,
    EditRefusal,
    EditRequest,
    LinePlace,
    Located,
    PinEdited,
    PinReplayed,
    RegionPlace,
    SuggestFacts,
    VerdictFacts,
    decide_edit,
    decide_new_suggestion,
    decide_new_verdict,
    evolve_edit,
    file_after,
    new_line_pin,
    new_region_pin,
)
from limn.pins.editing.values import ASSIGNEE_AGENT, NOTE_MAX
from limn.pins.idem import keyed_pin
from limn.pins.location.lookup import PinLocation
from limn.pins.location.mapping import anchor_of, comment_marker
from limn.pins.model import DonePin, OpenPin, Pin, PinNotFound, Record, Region, ReviewPin
from limn.pins.retention import unexpired
from limn.pins.store import pin_index
from limn.pins.suggestion import Suggestion
from limn.pins.verdict import verdict_of, whole_figure
from limn.platform.files import tex_lines
from limn.runtime.documents import Doc, doc_by_key, document_authority_target
from limn.security.access import PostAuthority, require_authority


def located(loc: PinLocation | None) -> Located | None:
    """A pin location found on disk (PinContext.locate) as the value limn.pins.editing.rules records: absolute path and rel."""
    return None if loc is None else Located(str(loc.path), loc.rel)


def add_pin(ctx: PinContext, D: Doc, request: AddRequest, actor: PostAuthority) -> OpenPin | PinReplayed | AddRefusal:
    """Saves a new pin in document D from a parsed POST /api/pin body (limn.pins.editing.input.parse_add) -> the new open pin. A
    LaTeX document gets a line pin with its anchor (which skips the comment lines of the file's kind,
    comment_marker), the author and - since 0.3.2 (ADR-0006) - file_rel next to the absolute file; a view-only
    document gets a region pin, and so does a figure document for a region pick (a drag that found no lines). Queues
    mention/assigned notices and emits them after the write.

    A request with a suggested edit is decided first (limn.pins.editing.rules.decide_new_suggestion): only a line pin
    of a document that takes suggestions (D.takes_suggestions: LaTeX and Markdown) takes one, within its limits, and
    its base must be what the pin's lines read in the same snapshot the anchor is taken from. A refusal is returned and nothing is written - no id is
    allocated and no transaction runs.

    A request with a verdict is decided inside the transaction, before an id is allocated
    (limn.pins.editing.rules.decide_new_verdict), against facts read just before the pin lock is taken (_read_verdict):
    the keys D declares then (ctx.verdict_keys), whether the principal may make one (Principal.authors_verdicts) and -
    for a figure document's pin that names its page's whole figure (el.path == [el.id]) - whether the map of the pin's
    build (the pdf_build it sent, else the build on screen, read once and recorded, so the pin records the build that
    was checked) has that element as the root of the pin's page (ctx.builds.page_root). Reading them outside the lock
    keeps a word file or map copy that stalls from holding up every other pin operation. Its suggestion, if it sent
    one, is never decided - the verdict decision refuses every such request - so the verdict's refusals come in their
    own order. A refusal writes nothing of its own (a re-sync of the stored pins may still be written, as for any
    transaction). A failed checked manuscript read propagates before any anchor or pin is saved.

    A request with an idempotency key (request.idem, limn.pins.idem) first looks, under the pin lock it then keeps
    through the transaction that would create the pin, for a pin of this instance that already holds the key - a live
    pin of any state or document, as stored, or a Trash entry still restorable. If one does, the result is PinReplayed
    with its id and no transaction runs: nothing is decided or written - no id, record, re-sync, notice, pins.md or
    pins_rev change - whatever its body says. Otherwise its suggestion is decided inside the transaction, against the
    snapshot of lines read before the lock; a refusal there writes nothing of its own (a re-sync may still be written,
    as for a verdict's refusal). A request without a key takes exactly the path it always has."""
    require_authority(actor, ctx.authority_scope, "add", document_authority_target(D))
    place = request.place
    # Manuscript text is read before taking the pin lock, as it was for line pins before this shared transaction.
    location = ctx.locate({"file": place.file}) if isinstance(place, LinePlace) else None
    lines, mtime = location.source.snapshot_checked() if location is not None else ([], 0.0)
    suggests = request.suggest is not None and request.verdict is None
    if suggests and request.idem is None:
        refused = _suggestion_refused(request, D, lines)
        if refused is not None:
            return refused
    author = actor.principal.authors_verdicts()
    # A verdict's facts are read before taking the pin lock, so a word file or map copy that stalls holds up only
    # this request.
    reads = None if request.verdict is None else _read_verdict(ctx, D, place, request.verdict, author)
    evs: list[Event | None] = []

    def fn(pins: list[Pin]) -> tuple[OpenPin | PinReplayed | AddRefusal, bool]:
        """Decide a keyed request's suggestion and the verdict, if one was asked for, then allocate one id, build
        either location kind, and queue notices in the same transaction.
        The build on screen is read once: a pin without pdf_build records the build its whole figure was checked on
        (read with that check, before the lock), not one published in between."""
        if request.idem is not None and suggests:
            refused = _suggestion_refused(request, D, lines)
            if refused is not None:
                return refused, False
        # The viewer echoes pdf_build from pick; an agent request without it uses the current build.
        checked_on = None if reads is None else reads.on_screen
        on_screen = ctx.builds.heading(D).build if checked_on is None else checked_on
        verdict = None
        if reads is not None:
            judged = decide_new_verdict(reads.asked, request, reads.facts)
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
                pin = new_line_pin(
                    place,
                    request,
                    pid,
                    at,
                    actor,
                    tags.mentions,
                    anchoring,
                    on_screen,
                    D.key,
                    located(ctx.locate({"file": place.file})),
                    verdict,
                )
            case RegionPlace():
                pin = new_region_pin(place, request, pid, at, actor, tags.mentions, on_screen, D.key, verdict)
        pins.append(pin)
        evs.append(ctx.make_event("mention", pin.record, actor, tags.notify, text=request.note))
        if request.assignee is not None and request.assignee != ASSIGNEE_AGENT:
            evs.append(ctx.make_event("assigned", pin.record, actor, [request.assignee], text=request.note))
        return pin, True

    with ctx.store.lock:  # re-entrant: the key lookup and the transaction that creates the pin hold it together
        if request.idem is not None:
            held = _key_holder(ctx, ctx.store.read_pins()[0], request.idem)
            if held is not None:
                return PinReplayed(held)
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def _suggestion_refused(request: AddRequest, D: Doc, lines: Sequence[str]) -> AddRefusal | None:
    """Why the request's suggestion keeps the pin from being written (decide_new_suggestion against the lines read
    before the lock), or None when it is accepted."""
    assert request.suggest is not None
    decided = decide_new_suggestion(request.suggest, request.place, D.takes_suggestions, lines)
    return None if isinstance(decided, Suggestion) else decided


def _key_holder(ctx: PinContext, pins: Sequence[Pin], key: str) -> int | None:
    """The id of the pin that already holds idempotency key `key`: among the live pins as stored, then the Trash
    entries still restorable now (an expired entry, like a purged one, holds no key). Called under the pin lock every
    pin and Trash write also holds, so no create, drop, restore or purge lands between this lookup and the create."""
    trash, _ = ctx.store.read_dropped()
    return keyed_pin(key, pins, unexpired(trash, ctx.trash_days, ctx.epoch()))


@dataclass(frozen=True)
class _VerdictReads:
    """What a new pin that asks for a verdict reads before the pin lock (_read_verdict): the verdict asked for, the
    facts decide_new_verdict checks it against inside the transaction, and the build on screen when the root check
    read it - for a whole-figure pin that sent no pdf_build, so the pin records the build its figure was checked on.
    on_screen is None when the check read no build on screen; the transaction then reads it itself."""

    asked: AskedVerdict
    facts: VerdictFacts
    on_screen: str | None


def _read_verdict(
    ctx: PinContext, D: Doc, place: LinePlace | RegionPlace, asked: AskedVerdict, author: bool
) -> _VerdictReads:
    """Read, before the pin lock is taken, what deciding a new pin's verdict needs
    (limn.pins.editing.rules.VerdictFacts): the keys D declares now (ctx.verdict_keys - the document owner's bounded
    read and parse of its word file) and whether the pin's page target holds. That is False only for a figure
    document's pin whose el names its page's whole figure (limn.pins.verdict.whole_figure) when the map of the pin's
    build - the pdf_build the request sent, else the build on screen, read here once - does not have that element as
    the root of the pin's page; only then is the build owner asked (ctx.builds.page_root, a stat of the map copy and
    its parse on a cache miss). Both facts are those of a moment just before the lock, not inside it. A build's map
    copy is written once, when the build is imported, so the root answer for the build the pin records is the same
    inside the lock; a word file changed in between is read by the next request. Reads no file itself."""
    keys = ctx.verdict_keys(D)
    fields = place.fields
    figure = whole_figure(fields) if D.has_element_map else None
    if figure is None:
        return _VerdictReads(asked, VerdictFacts(author, keys), None)
    sent = fields.get("pdf_build")
    if sent:
        holds = ctx.builds.page_root(D, sent, fields["page"], figure)
        return _VerdictReads(asked, VerdictFacts(author, keys, holds), None)
    on_screen = ctx.builds.heading(D).build
    holds = ctx.builds.page_root(D, on_screen, fields["page"], figure)
    return _VerdictReads(asked, VerdictFacts(author, keys, holds), on_screen)


def edit_pin(
    ctx: PinContext,
    pid: int,
    request: EditRequest,
    actor: PostAuthority,
    region: bool = False,
    suggestions: bool = False,
    *,
    pages: bool = True,
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
    file the pin will point at - so its base is compared with the lines it replaces after this edit; suggestions says
    the pin's document takes suggested edits (Doc.takes_suggestions: LaTeX and Markdown), the only ones whose line
    pins take a suggestion. pages
    says the pin's document has pages (not Doc.renders_in_browser): on one without, the edit removes every page field
    the record carries (limn.pins.editing.rules.evolve_edit). A failed checked anchor read propagates before
    saving the edit."""
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
        facts = (
            SuggestFacts(suggestions, None if source is None else tuple(source)) if request.sets_suggestion() else None
        )
        event = decide_edit(pin, request, typed_actor(actor), ctx.now(), clock, count, NOTE_MAX, facts, pages=pages)
        if not isinstance(event, PinEdited):
            return event, False
        span = event.span()
        anchoring = None
        if span is not None and where is not None:
            lines, mtime = where.source.snapshot_checked()
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
    (limn.pins.verdict.verdict_of - then no loc is read, limn.pins.editing.input.parse_edit_place), the document whose
    facts its loc is parsed against and whose capability decides a suggestion - the one it belongs to, or the first
    document for a pin whose document this run does not serve - and pages, whether the pin has pages. pages comes from
    the pin's own record by the rule every write of a pin uses (PinContext.has_pages, limn.pins.pages.keep_pages):
    False only for a document the browser draws, True for one this run does not serve - never from the first
    document that stands in for it. The edit is placed (parse_edit_place) and written (edit_pin) with it. A verdict
    never leaves a pin, and the editing rules check the pin again under the lock."""

    region: bool
    verdict: bool
    document: Doc
    pages: bool


@dataclass(frozen=True)
class EditScope:
    """Read a pin's region kind, verdict, owning document and pages before parsing an edit's location. has_pages is
    the run's answer for a pin record (PinContext.has_pages)."""

    read_pins: Callable[[], tuple[list[Pin], list[int]]]
    docs: Callable[[], Sequence[Doc]]
    pin_doc_key: Callable[[Record], str]
    has_pages: Callable[[Record], bool]

    def __call__(self, pid: int) -> EditTarget:
        """The pin's EditTarget. An id that is not among the live pins reads as a line pin without a verdict in the
        first document, with that document's pages; the pin transaction answers a pin that is still missing as not
        found."""
        pins, _ = self.read_pins()
        docs = self.docs()
        i = pin_index(pins, pid)
        if i is None:
            first = docs[0]
            return EditTarget(False, False, first, pages=not first.renders_in_browser)
        pin = pins[i]
        return EditTarget(
            isinstance(pin.core.place, Region),
            verdict_of(pin.record) is not None,
            doc_by_key(docs, self.pin_doc_key(pin.record)) or docs[0],
            pages=self.has_pages(pin.record),
        )


@dataclass(frozen=True)
class PinEditing:
    """Pin creation and editing bound to one application's context factory."""

    context: Callable[[], PinContext]

    def add_pin(self, D: Doc, request: AddRequest, actor: PostAuthority) -> OpenPin | PinReplayed | AddRefusal:
        """Create one pin and emit notices after its transaction, answer the pin that already holds its idempotency
        key, or return why its suggested edit or verdict is refused."""
        ctx = self.context()
        require_authority(actor, ctx.authority_scope, "add", document_authority_target(D))
        return add_pin(ctx, D, request, actor)

    def keyed_pin(self, D: Doc, key: str, actor: PostAuthority) -> int | None:
        """The id of the pin that already holds idempotency key `key`, or None - the question a viewer asks before it
        places a queued pin again (POST /api/pin with replay_only). Asked with the authority a new pin needs, and
        answered under the pin lock from the stored pins and the restorable Trash, as add_pin's own lookup is: nothing
        is decided or written, whichever way it is answered."""
        ctx = self.context()
        require_authority(actor, ctx.authority_scope, "add", document_authority_target(D))
        with ctx.store.lock:
            return _key_holder(ctx, ctx.store.read_pins()[0], key)

    def edit_pin(
        self,
        pid: int,
        request: EditRequest,
        actor: PostAuthority,
        region: bool = False,
        suggestions: bool = False,
        *,
        pages: bool = True,
    ) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
        """Edit one pin under the store lock and emit accepted notices; suggestions: the pin's document takes suggested
        edits (Doc.takes_suggestions); pages: it has pages (not one the browser draws)."""
        ctx = self.context()
        require_authority(actor, ctx.authority_scope, "edit", pid)
        return edit_pin(ctx, pid, request, actor, region, suggestions, pages=pages)

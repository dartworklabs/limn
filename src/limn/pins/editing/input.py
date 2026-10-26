"""Parse pin creation and editing bodies in their contract order."""

from collections.abc import Collection
from dataclasses import dataclass, replace

from limn.pins.editing.fields import (
    parse_assignee,
    parse_kind_req,
    parse_note,
    parse_scope,
    parse_suggest,
    parse_verdict,
)
from limn.pins.editing.location import parse_loc, parse_region
from limn.pins.editing.rules import (
    NULLABLE_TARGETS,
    AddRequest,
    EditRequest,
    LinePlace,
    Place,
    RegionPlace,
    RemoveSuggestion,
    SuggestChange,
    UnreadLoc,
)
from limn.pins.suggestion import Suggestion
from limn.web.errors import InputRejected
from limn.web.parse import DocumentFacts, Json, int_field, parse_mention_hints

ADD_FIELDS = (
    "file",
    "name",
    "page",
    "lo",
    "hi",
    "raw_lo",
    "raw_hi",
    "kind",
    "via",
    "score",
    "frac",
    "note",
    "scope",
    "quote",
    "pdf_build",
    "el",
)
REGION_FIELDS = ("page", "frac", "note", "quote", "pdf_build", "el")
REGION_EDIT_REFUSAL = "줄이 없는 영역 핀에는 줄 범위가 없습니다 — 메모(note)와 영역(loc: page, frac)만 고칩니다."
NOTHING_TO_CHANGE = InputRejected(
    "바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).", "nothing_to_change"
)


def parse_add(d: Json, known: Collection[str], facts: DocumentFacts) -> AddRequest | InputRejected:
    """A POST /api/pin body for the request's document -> the new pin's validated place and fields, or the first
    field refused, in the contract's order: the location first - a region (parse_region, which refuses
    file/lo/hi/scope) on a view-only document, and on a figure document when the body names no file, lo or hi (an
    element drawn without code, docs/handbook/api.md §그림 문서의 pick·핀); lines (parse_loc, which reads the
    named file) otherwise. A figure document's place keeps the body's el (parse_el). Then note, kind_req, mention hints,
    assignee (known: the logins supplied by EditingRequests) and suggest - its shape alone (parse_suggest; null is
    absent). Whether this pin may carry the suggestion is decided against the document and the file before it is
    written (limn.pins.editing.rules.decide_new_suggestion). Last the verdict, taken as sent (parse_verdict; null is
    absent) - it refuses nothing here, since its refusals come after the role check in their own order, inside the
    store transaction (limn.pins.editing.rules.decide_new_verdict)."""
    place: Place
    if facts.view_only or (facts.has_element_map and all(d.get(k) is None for k in ("file", "lo", "hi"))):
        region = parse_region({k: d[k] for k in REGION_FIELDS + ("file", "lo", "hi", "scope") if k in d}, facts)
        if isinstance(region, InputRejected):
            return region
        place = RegionPlace(region.to_record())
    else:
        named = {k: d[k] for k in ADD_FIELDS if k in d}
        line = parse_loc(named, facts)
        if isinstance(line, InputRejected):
            return line
        place = LinePlace(line.to_record(), frozenset(key for key, value in named.items() if value is not None))
    note = parse_note(d.get("note"))
    if isinstance(note, InputRejected):
        return note
    kind_req = parse_kind_req(d.get("kind_req"))
    if isinstance(kind_req, InputRejected):
        return kind_req
    hints = parse_mention_hints(d.get("mentions"))
    if isinstance(hints, InputRejected):
        return hints
    assignee = parse_assignee(d.get("assignee"), known)
    if isinstance(assignee, InputRejected):
        return assignee
    suggest: Suggestion | None = None
    if d.get("suggest") is not None:
        sent = parse_suggest(d["suggest"])
        if isinstance(sent, InputRejected):
            return sent
        suggest = sent
    return AddRequest(place, note, kind_req, assignee, tuple(hints), suggest, parse_verdict(d.get("verdict")))


@dataclass(frozen=True)
class EditBody:
    """An edit body with every field checked except loc, which is checked against the pin's own document once the
    pin is known - or left unread for a verdict pin (parse_edit_place). request.place is still None."""

    loc: Json | None
    request: EditRequest


def parse_edit(d: Json, known: Collection[str]) -> EditBody | InputRejected:
    """A POST /api/pins/{id}/edit body -> its checked fields, or the first one refused, in the contract's order.

    note (null is the empty note), note_append (a non-blank string of at most 2000 characters), loc (an object),
    lo/hi (integers), scope, kind, kind_req, mention hints, assignee (known: the logins from EditingRequests) and
    suggest - sent as {base, text} it sets or replaces the pin's suggestion (parse_suggest), sent as null it removes
    it, absent it leaves it. A `verdict` key, with any value, is recorded as sent: no edit sets a verdict, and the
    editing rules refuse it (limn.pins.editing.rules.decide_edit, verdict_fixed) once the pin is known. loc, lo, hi,
    scope, kind and kind_req sent as null are absent values but are recorded by name (EditRequest.sent_null), so a
    verdict pin refuses them as verdict_fixed too. base_rev is required unless the edit is a note_append without a
    suggest, and something must be changed (_changes) - a sent verdict counts, and so does a field sent as null, which
    only a verdict pin answers: on any other pin parse_edit_place finds nothing to change.
    """
    note: str | None = None
    if "note" in d:
        parsed = parse_note(d.get("note"))
        if isinstance(parsed, InputRejected):
            return parsed
        note = parsed
    note_append = d.get("note_append")
    if note_append is not None:
        if not isinstance(note_append, str):
            return InputRejected("note_append 는 문자열이어야 합니다.", "bad_note_append")
        if not note_append.strip():
            return InputRejected("덧붙일 메모가 비어 있습니다.", "note_append_empty")
        if len(note_append) > 2000:
            return InputRejected("덧붙일 메모가 너무 깁니다(2000자 이하).", "note_append_too_long")
    loc = d.get("loc")
    if loc is not None and not isinstance(loc, dict):
        return InputRejected("loc 는 객체여야 합니다.", "bad_loc")
    lo = int_field(d["lo"], "lo") if d.get("lo") is not None else None
    if isinstance(lo, InputRejected):
        return lo
    hi = int_field(d["hi"], "hi") if d.get("hi") is not None else None
    if isinstance(hi, InputRejected):
        return hi
    scope = parse_scope(d.get("scope"))
    if isinstance(scope, InputRejected):
        return scope
    kind = d.get("kind")
    if kind is not None and (not isinstance(kind, str) or len(kind) > 80):
        return InputRejected("kind 가 올바르지 않습니다.", "bad_kind")
    kind_req = parse_kind_req(d.get("kind_req"))  # a note-level value that can be changed even on a closed pin
    if isinstance(kind_req, InputRejected):
        return kind_req
    hints = parse_mention_hints(d.get("mentions"))
    if isinstance(hints, InputRejected):
        return hints
    # like kind_req, changeable on a closed pin (leaves an ev=assign)
    assignee = parse_assignee(d.get("assignee"), known)
    if isinstance(assignee, InputRejected):
        return assignee
    suggest: SuggestChange | None = None
    if "suggest" in d:
        if d["suggest"] is None:
            suggest = RemoveSuggestion()
        else:
            sent = parse_suggest(d["suggest"])
            if isinstance(sent, InputRejected):
                return sent
            suggest = sent
    base_given = "base_rev" in d
    if not base_given and (note_append is None or suggest is not None):
        return InputRejected("base_rev 가 필요합니다(카드를 열 때 받은 rev).", "base_rev_required")
    base = int_field(d["base_rev"], "base_rev") if base_given else None
    if isinstance(base, InputRejected):
        return base
    request = EditRequest(
        base,
        note,
        note_append,
        None,
        lo,
        hi,
        scope,
        kind,
        kind_req,
        assignee,
        tuple(hints),
        suggest,
        "verdict" in d,
        frozenset(name for name in NULLABLE_TARGETS if name in d and d[name] is None),
    )
    if not (_changes(request, loc) or request.sent_null):
        return NOTHING_TO_CHANGE
    return EditBody(loc, request)


def _changes(request: EditRequest, loc: Json | None) -> bool:
    """Does the edit change something on a pin without a verdict: a re-placement (loc), a field sent with a value, a
    suggestion set or removed, or a verdict named? Mention hints alone change nothing, and neither do the target
    fields sent as null (EditRequest.sent_null), which such a pin reads as absent."""
    return (
        loc is not None
        or request.note is not None
        or request.lo is not None
        or request.hi is not None
        or request.scope is not None
        or request.kind is not None
        or request.note_append is not None
        or request.kind_req is not None
        or request.assignee is not None
        or request.suggest is not None
        or request.verdict_sent
    )


def parse_edit_place(
    body: EditBody, region: bool, facts: DocumentFacts, *, verdict: bool
) -> Place | UnreadLoc | None | InputRejected:
    """An edit's re-placement checked against the pin's own document (facts), or None when the edit sends no loc.

    verdict says the stored pin carries a verdict (limn.pins.editing.service.EditTarget); a body that sends one counts
    too. Such a pin keeps its place, so nothing of where it points is checked here: a loc comes back unread
    (UnreadLoc), and lo/hi/scope/kind and the fields sent as null stay in the request, for the editing rules to
    refuse the edit as verdict_fixed (limn.pins.editing.rules.decide_edit) - not with the location's own refusal, and
    without opening the file a loc names. Any other pin reads a field sent as null as absent, so an edit that sends
    nothing else is nothing_to_change, as parse_edit answers an empty edit. Otherwise a region pin (a view-only PDF's,
    or a figure element drawn without code) refuses lo/hi/scope/kind first. Then loc is parsed like a new pin's
    location (parse_region for a region pin, parse_loc for a line pin), a figure document's el included (parse_el):
    the re-placement carries the el it names, or none, and so drops the old one. pdf_build records which build frac's
    coordinates belong to, so a loc that re-places frac takes the one sent or the build on screen, and a loc without
    frac cannot change it."""
    request = body.request
    if verdict or request.verdict_sent:
        return None if body.loc is None else UnreadLoc()
    if not _changes(request, body.loc):
        return NOTHING_TO_CHANGE
    if region and (
        request.lo is not None or request.hi is not None or request.scope is not None or request.kind is not None
    ):
        return InputRejected(REGION_EDIT_REFUSAL, "no_source_lines")
    loc = body.loc
    if loc is None:
        return None
    if region:
        area = parse_region(loc, facts)
        if isinstance(area, InputRejected):
            return area
        return RegionPlace(replace(area, pdf_build=_placed_build(loc, area.pdf_build, facts)).to_record())
    line = parse_loc(loc, facts)
    if isinstance(line, InputRejected):
        return line
    return LinePlace(
        replace(line, pdf_build=_placed_build(loc, line.pdf_build, facts)).to_record(),
        frozenset(key for key, value in loc.items() if value is not None),
    )


def _placed_build(loc: Json, sent: str | None, facts: DocumentFacts) -> str | None:
    """The pdf_build an edit's re-placement records: the one sent, else the build on screen, when loc re-places frac
    (its coordinates belong to that build); None - the pin's own is kept - when loc sends no frac."""
    if loc.get("frac") is None:
        return None
    current = facts.current_build()  # read even when one was sent, as it always has been
    return sent if sent is not None else current

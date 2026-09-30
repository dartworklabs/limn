"""Parse pin creation and editing bodies in their contract order."""

from collections.abc import Collection
from dataclasses import dataclass, replace

from limn.pins.editing.fields import parse_assignee, parse_kind_req, parse_note, parse_scope
from limn.pins.editing.location import parse_loc, parse_region
from limn.pins.editing.rules import AddRequest, EditRequest, LinePlace, Place, RegionPlace
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
REGION_EDIT_REFUSAL = "보기 전용 문서의 핀에는 줄 범위가 없습니다 — 메모(note)와 영역(loc: page, frac)만 고칩니다."


def parse_add(d: Json, known: Collection[str], facts: DocumentFacts) -> AddRequest | InputRejected:
    """A POST /api/pin body for the request's document -> the new pin's validated place and fields, or the first
    field refused, in the contract's order: the location first - a region (parse_region, which refuses
    file/lo/hi/scope) on a view-only document, and on a figure document when the body names no file, lo or hi (an
    element drawn without code, docs/handbook/api.md §그림 문서의 pick·핀); lines (parse_loc, which reads the
    named file) otherwise. A figure document's place keeps the body's el (parse_el). Then note, kind_req, mention hints
    and assignee (known: the logins supplied by EditingRequests)."""
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
    return AddRequest(place, note, kind_req, assignee, tuple(hints))


@dataclass(frozen=True)
class EditBody:
    """An edit body with every field checked except loc, which is checked against the pin's own document once the
    pin is known (parse_edit_place). request.place is still None."""

    loc: Json | None
    request: EditRequest


def parse_edit(d: Json, known: Collection[str]) -> EditBody | InputRejected:
    """A POST /api/pins/{id}/edit body -> its checked fields, or the first one refused, in the contract's order.

    note (null is the empty note), note_append (a non-blank string of at most 2000 characters), loc (an object),
    lo/hi (integers), scope, kind, kind_req, mention hints and assignee (known: the logins from EditingRequests).
    base_rev is required unless the edit is a note_append, and something must be changed.
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
    base_given = "base_rev" in d
    if not base_given and note_append is None:
        return InputRejected("base_rev 가 필요합니다(카드를 열 때 받은 rev).", "base_rev_required")
    base = int_field(d["base_rev"], "base_rev") if base_given else None
    if isinstance(base, InputRejected):
        return base
    moves = loc is not None or lo is not None or hi is not None
    if not (
        note is not None
        or moves
        or scope is not None
        or kind is not None
        or note_append is not None
        or kind_req is not None
        or assignee is not None
    ):
        return InputRejected(
            "바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).", "nothing_to_change"
        )
    return EditBody(
        loc, EditRequest(base, note, note_append, None, lo, hi, scope, kind, kind_req, assignee, tuple(hints))
    )


def parse_edit_place(body: EditBody, region: bool, facts: DocumentFacts) -> Place | None | InputRejected:
    """An edit's re-placement checked against the pin's own document (facts), or None when the edit sends no loc.

    A region pin (a view-only PDF's, or a figure element drawn without code) refuses lo/hi/scope/kind first. Then loc is
    parsed like a new pin's location (parse_region for a region pin, parse_loc for a line pin), a figure document's el
    included (parse_el): the re-placement carries the el it names, or none, and so drops the old one. pdf_build records
    which build frac's coordinates belong to, so a loc that re-places frac takes the one sent or the build on screen,
    and a loc without frac cannot change it."""
    request = body.request
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

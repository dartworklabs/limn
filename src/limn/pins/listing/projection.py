"""How the API shows stored pins: the computed fields of GET /api/pins and the Trash list (docs/handbook/api.md).

GET /api/pins returns each stored record plus fields computed on every read and never stored: `state` (the name of
the pin's state type), `rel` (its overlaps with other open line pins), `est` (whether its mark is only an estimate on
the PDF on screen), `doc`, `addressed` and `fyi` (who it is handed to or tags for reference), and for a claim written
before claim_ts existed the claim's start epoch - and, for a figure pin with an element, `mark`, `mark_page` and
`el_sync` on its document's current map (docs/handbook/api.md §그림 문서의 pick·핀), or, for a line pin of a document
a LaTeX build prints, `boxes`: where its own lines print on the build on screen, the same pieces a pick and a snippet
answer for those lines (docs/adr/0049-pin-marks-follow-the-range.md). A verdict pin that a newer
verdict pin about the same target supersedes also gets `superseded_by`, that pin's number (limn.pins.verdict.superseded_by,
ADR-0023): it follows `fyi` and is never stored. A pin with a suggested edit
also gets `suggest_state` (suggest_view), last, here and in every change response's `pin` (public_record).
GET /api/pins/dropped returns the Trash with `expires_ts`. Both answers are the agent contract: field names, order
and values must not change.

Everything here is pure. What only the instance knows arrives as arguments: how a record is shown (the composition
root's public(): public_record() with where the pin's file is on this machine now), which document a pin belongs to,
the estimation facts
of a document's builds (read at most once per document, only for documents with a listed pin), a figure document's
current map (asked at most once per document, only for one with a listed pin that carries an element), where a
document's line ranges print (asked the same way, only for one with a listed line pin), the overlaps
already computed over all rows, when a Trash entry expires, and the clock.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TypeAlias

from limn.pins.element import element_of
from limn.pins.idem import IDEM_FIELD
from limn.pins.location.mapping import anchor_stands, mark_wire
from limn.pins.location.position import EstContext, epoch, pin_est
from limn.pins.mentions import addressed_to, fyi_mentions_to
from limn.pins.model import OpenPin, StateName, TrashedPin, parse_pin, state_of
from limn.pins.needs import BoxesFor, FollowElement
from limn.pins.suggestion import SuggestState, lines_text, suggest_state, suggestion_of
from limn.pins.thread import claim_holds
from limn.platform.values import is_finite_num, is_int, is_num, wire_value

# One stored pin (or Trash entry) as the store read it, and one record as the API returns it: JSON objects.
Row: TypeAlias = Mapping[str, Any]
Json: TypeAlias = dict[str, Any]
# How the API shows a record before the computed fields: a copy placed on this machine (server.public()).
Show: TypeAlias = Callable[[Row], Json]
# When a Trash entry expires, in epoch seconds, or None when its age cannot be read (pin listing collaborator).
ExpiresTs: TypeAlias = Callable[[TrashedPin], float | None]


def pin_state(r: Row) -> StateName:
    """'open' | 'review' | 'done' - a computed field, never stored (docs/handbook/api.md §검토 대기): the name of the
    state type limn.pins.model.state_of gives r, so the API and the transitions read one rule.

    Awaiting review is the shape done=true plus review=true. Because done is still true, the legacy contract
    keeps working as-is - GET /api/pins (open pins only), the pins.md open table, claim (409 on done), line
    matching, and overlap computation all treat an awaiting-review pin as "the agent's part is finished".
    An old server or old viewer just sees it as done, and nothing breaks. A legacy done:true record with no
    review field stays plain done - reading it never triggers a migration write."""
    return state_of(r).state


def public_record(r: Row, place: tuple[str, str] | None, suggest: SuggestState | None = None) -> Json:
    """A record as the API returns it (docs/handbook/api.md §핀 파일의 위치, ADR-0006): a copy with rev defaulted to 0
    (a missing or non-integer rev) and without the stored `idem` (a new pin's idempotency key, limn.pins.idem: a
    write-side identity no reader is shown), the stored `file_rel` and any stored `rel_path` or `suggest_state` (both
    are this server's answers, never a value a hand edit or another version left behind). suggest is the
    suggestion's state the edge computed (suggest_view), appended last as `suggest_state` when given. place is where the
    composition root finds a line pin's file under the manuscript root now - (absolute path, path relative to the
    root) - and becomes `file` and `rel_path`; with None (a region pin, or a file it cannot locate) the stored file
    stays and there is no rel_path. rel_path is always this server's answer, never a value an older version left
    behind. The API never carries a NaN, an Infinity or an integer no float holds (the store keeps them in a
    hand-edited or legacy line): a `frac` or `el.frac` with any such entry is None as a whole (a mark drawn from the
    finite entries would sit at a made-up position; limn.pins.element.element_of and the viewer skip such a frac
    too), and every other stored number - synced_at, score, fill, claim_until, claim_ts, eta_ts, and any number inside an
    anchor, a thread entry or a field this version does not know - is None. The stored line is not touched. Never
    changes r."""
    out = dict(r)
    out["rev"] = out["rev"] if is_int(out.get("rev")) else 0
    out.pop(IDEM_FIELD, None)
    out.pop("file_rel", None)
    out.pop("rel_path", None)
    out.pop("suggest_state", None)
    if place is not None:
        out["file"], out["rel_path"] = place
    if "frac" in out:
        out["frac"] = _wire_frac(out["frac"])
    el = out.get("el")
    if isinstance(el, dict) and "frac" in el:
        out["el"] = {**el, "frac": _wire_frac(el["frac"])}
    shown = {k: wire_value(v) for k, v in out.items()}
    if suggest is not None:
        shown["suggest_state"] = suggest
    return shown


def suggest_view(r: Row, lines: Sequence[str] | None) -> SuggestState | None:
    """The `suggest_state` of record r (docs/adr/0020-suggested-edit-pins.md D2): None when r carries no well-formed
    suggestion (limn.pins.suggestion.suggestion_of); else whether its lines lo..hi of lines - the current lines of
    r's file as the edge read them, after the store's re-sync, or None when that file is not located - still read as
    its base (limn.pins.suggestion.suggest_state; a stale pin is "unknown"). Never stored; never changes r."""
    suggestion = suggestion_of(r.get("suggest"))
    if suggestion is None:
        return None
    lo, hi = r.get("lo"), r.get("hi")
    current = lines_text(lines, lo, hi) if lines is not None and is_int(lo) and is_int(hi) else None
    return suggest_state(suggestion, current, r.get("stale") is True)


def _wire_frac(frac: object) -> object:
    """A stored frac as the wire can carry it: None when it is a list with any non-finite number (the whole field: a
    box with one made-up coordinate would put the mark at a made-up position), else a copy of it. Anything that is
    not a list - a string, a missing value, a record the store keeps as it is - is unchanged. Finite numbers, 0.0 and
    1.0 included, pass exactly."""
    if not isinstance(frac, list):
        return frac
    if any(is_num(v) and not is_finite_num(v) for v in frac):
        return None
    return list(frac)


# The box compared with when neither the element nor the pin recorded one. Its origin is off the page (-1, -1), so no
# element's box - x and y in 0..1 - is within FOLLOW_EPS of it, however small the element or near the page origin:
# such a pin is never "ok".
NO_FRAC: tuple[float, float, float, float] = (-1.0, -1.0, 0.0, 0.0)


def no_figure_maps(key: str) -> None:
    """No element-position lookup for an instance without figure documents."""
    return None


def no_line_boxes(_key: str) -> None:
    """No mark lookup for an instance whose documents print no line pin's lines."""
    return None


def _shown_file(value: object) -> str | None:
    """The file a shown record names, when it names one. public_record keeps a line pin's stored file or replaces it
    with where this machine holds it now (ADR-0006), and both are strings; anything else is a record whose place was
    never lifted whole, and there is no file to ask about.

    The second case is `object()` and not `_`: an irrefutable case needs assert_never (tools/check_fitness.py), and
    the type checker wants the match to exhaust `object` rather than fall out of it."""
    match value:
        case str() as file:
            return file
        case object():
            return None


def line_marks(anchor: Row | None, shown: Json, boxes: BoxesFor | None, lines: Sequence[str] | None) -> Json:
    """Where the lines of line pin `shown` print on the build its document has on screen: {} unless its stored anchor
    (the parsed record's, None when it has none) still stands on its lo..hi in lines - the norm()-ed lines of the file the answer names, as they are now - and boxes answers
    pieces for that file and range; else {"boxes": [...]} as mark_wire shapes them.

    The anchor is asked first (limn.pins.location.mapping.anchor_stands: its head at lo, its tail at hi). Line matching
    follows open pins alone and a lost anchor keeps its old numbers, so a closed or lost pin's lo..hi can name text it
    never held, and the mark of those numbers would sit on that text (#547). A pin whose text is not on its lines - or
    whose file's lines are not known (lines None) - gets no key, and its range is never asked about: the forward pass
    costs a process per line. Every state follows this one rule.

    The file is the one the answer itself names, not the one the record stores: a pin written in another checkout
    carries that checkout's path, and the mark must describe the file this answer points the reader at. A range with
    no pieces leaves the key out rather than carrying [], the same rule as a pick's default rung and a snippet's
    (limn.pins.location.mapping.mark_wire). Never stored; never changes shown."""
    file, lo, hi = _shown_file(shown.get("file")), shown.get("lo"), shown.get("hi")
    if boxes is None or lines is None or file is None or not is_int(lo) or not is_int(hi):
        return {}
    if not anchor_stands(anchor, lo, hi, lines):
        return {}
    pieces = boxes(file, lo, hi)
    return {"boxes": mark_wire(pieces)} if pieces else {}


def no_current_lines(_r: Row) -> None:
    """No file is read: nothing confirms a pin's text is on its lines, so no pin gets a mark of them."""
    return None


def element_marks(r: Row, fmap: FollowElement | None) -> Json:
    """The read-time position of pin r's element on its figure document's current map: {} unless r carries a well-formed
    el (limn.pins.element) and fmap answers its current position; else el_sync and, when the
    element still exists, mark ([x, y, w, h]) and mark_page before it. Where the element was when pinned is el.frac
    (its box then); a pin without it is compared by its own frac, and a pin with neither by NO_FRAC, so it is never
    "ok". The page is the pin's page. Never stored; never changes r."""
    el = element_of(r.get("el"))
    if el is None or fmap is None:
        return {}
    frac = r.get("frac")
    then = el.frac
    if then is None and isinstance(frac, list) and len(frac) == 4 and all(is_finite_num(v) for v in frac):
        then = (float(frac[0]), float(frac[1]), float(frac[2]), float(frac[3]))
    page = r.get("page")
    got = fmap(el.id, page if is_int(page) else 0, then or NO_FRAC)
    if got.page is None or got.frac is None:
        return {"el_sync": got.sync}
    return {"mark": list(got.frac), "mark_page": got.page, "el_sync": got.sync}


def pin_view(
    r: Row,
    shown: Json,
    rel: list[Json],
    est: bool,
    doc: str,
    now: float,
    fmap: FollowElement | None = None,
    superseded_by: int | None = None,
    boxes: BoxesFor | None = None,
    lines: Sequence[str] | None = None,
) -> Json:
    """One GET /api/pins record: shown (r as the API shows it) followed by rel, est, doc, state, addressed and fyi, in
    that order, then superseded_by - only when a newer verdict pin supersedes this one, the number of the pin that is
    its target's current verdict (limn.pins.verdict.superseded_by) - then, for a figure pin with an element on fmap,
    its document's current map, mark, mark_page and el_sync (element_marks), and for a line pin whose anchor stands on
    its lines in lines - its file's norm()-ed lines now - and whose lines boxes answers for, `boxes` (line_marks). The two never meet: a figure's mark comes from its element map and a line pin's
    from where its lines print. A claim that holds at epoch now but was
    written before claim_ts existed also gets claim_ts, its start epoch read from claimed_at (the viewer's "since
    20:02 (23 min in)"); none when claimed_at is not a readable time. A suggest_state that shown carries
    (public_record) moves to the very end, so it is the last field here as in a change response's pin. Never changes r
    or shown."""
    pin = parse_pin(r)
    rec = dict(shown, rel=rel, est=est, doc=doc, state=pin.state, addressed=addressed_to(pin), fyi=fyi_mentions_to(pin))
    if superseded_by is not None:
        rec["superseded_by"] = superseded_by
    rec.update(element_marks(r, fmap))
    rec.update(line_marks(pin.core.anchor, shown, boxes, lines))
    if claim_holds(r, now) and not is_num(r.get("claim_ts")):
        ts = epoch(r.get("claimed_at"))
        if ts is not None:
            rec["claim_ts"] = ts
    if "suggest_state" in rec:
        rec["suggest_state"] = rec.pop("suggest_state")
    return rec


def pins_payload(
    rows: Sequence[Row],
    allp: bool,
    rel: Mapping[int, list[Json]],
    show: Show,
    doc_of: Callable[[Row], str],
    est_context: Callable[[str], EstContext | None],
    now: float,
    figure_map: Callable[[str], FollowElement | None] = no_figure_maps,
    superseded: Mapping[int, int] | None = None,
    line_boxes: Callable[[str], BoxesFor | None] = no_line_boxes,
    current_lines: Callable[[Row], Sequence[str] | None] = no_current_lines,
) -> list[Json]:
    """GET /api/pins: the open pins of rows in row order (every pin when allp), each as pin_view() gives it.

    rel is the overlaps of all rows (limn.pins.location.position.overlaps_by_id; a listed pin without an entry has []).
    superseded is the supersession of all rows (limn.pins.verdict.superseded_by: {pin id: current verdict's id}), so
    an open verdict pin is told it is superseded by a closed newer one that the default list does not show.
    doc_of names a pin's document and est_context gives the estimation facts of a document by key, or None when the
    instance no longer serves it - then est is True (placed on a PDF that is not on screen). est_context is asked
    once per document, and only for documents with a listed pin, since it reads that document's build history.
    figure_map binds a build-owned element-position query by document key, never a parsed map;
    it is asked at most once per document, and only for a document with a listed pin that carries an el.
    line_boxes binds a build-owned "where do these lines print" query by document key, never a PDF or a page folder;
    it is asked at most once per document too, and only for a document with a listed line pin that is not a figure's
    element - the answer costs one process per line of text, and this route answers every open pin at once.
    current_lines gives the norm()-ed lines of the file a record's file is found at now, or None when it is not located
    or cannot be read; it is asked only for a pin whose document has an asker, since only that pin's anchor is checked
    against its lines before a mark is measured (line_marks). The caller reads each file once per call."""
    ctxs: dict[str, EstContext | None] = {}
    maps: dict[str, FollowElement | None] = {}
    askers: dict[str, BoxesFor | None] = {}
    out = []
    for r in rows:
        if not (allp or state_of(r) is OpenPin):
            continue
        k = doc_of(r)
        if k not in ctxs:
            ctxs[k] = est_context(k)
        ctx = ctxs[k]
        fmap = ask = lines = None
        if element_of(r.get("el")) is not None:
            if k not in maps:
                maps[k] = figure_map(k)
            fmap = maps[k]
        elif is_int(r.get("lo")) and is_int(r.get("hi")):
            if k not in askers:
                askers[k] = line_boxes(k)
            ask = askers[k]
            lines = current_lines(r) if ask is not None else None
        est = pin_est(r, ctx) if ctx is not None else True
        out.append(
            pin_view(r, show(r), rel.get(r["id"], []), est, k, now, fmap, (superseded or {}).get(r["id"]), ask, lines)
        )
    return out


def dropped_payload(entries: Iterable[TrashedPin], show: Show, expires_ts: ExpiresTs) -> list[Json]:
    """GET /api/pins/dropped: the Trash entries (already without expired ones) ordered by dropped_at, each as show
    gives its stored record plus `expires_ts` - when it leaves the Trash, rounded to milliseconds, for the viewer's
    "gone in N days" free of the browser's time zone - when expires_ts knows it. The order of entries with the same or
    no dropped_at is the entries' order."""
    out = []
    for entry in sorted(entries, key=_dropped_at):
        rec, exp = show(entry.record), expires_ts(entry)
        if exp is not None:
            rec["expires_ts"] = round(exp, 3)
        out.append(rec)
    return out


def _dropped_at(entry: TrashedPin) -> str:
    """The Trash list's sort key: the entry's dropped_at, "" when it has none."""
    return entry.dropped.at if entry.dropped is not None else ""

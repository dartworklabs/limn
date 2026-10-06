"""How the API shows stored pins: the computed fields of GET /api/pins and the Trash list (docs/handbook/api.md).

GET /api/pins returns each stored record plus fields computed on every read and never stored: `state` (the name of
the pin's state type), `rel` (its overlaps with other open line pins), `est` (whether its mark is only an estimate on
the PDF on screen), `doc`, `addressed` and `fyi` (who it is handed to or tags for reference), and for a claim written
before claim_ts existed the claim's start epoch - and, for a figure pin with an element, `mark`, `mark_page` and
`el_sync` on its document's current map (docs/handbook/api.md §그림 문서의 pick·핀). GET /api/pins/dropped returns the Trash
with `expires_ts`. Both answers are the agent contract: field names, order and values must not change.

Everything here is pure. What only the instance knows arrives as arguments: how a record is shown (the composition
root's public(): public_record() with where the pin's file is on this machine now), which document a pin belongs to,
the estimation facts
of a document's builds (read at most once per document, only for documents with a listed pin), a figure document's
current map (asked at most once per document, only for one with a listed pin that carries an element), the overlaps
already computed over all rows, when a Trash entry expires, and the clock.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TypeAlias

from limn.pins.element import element_of
from limn.pins.location.position import EstContext, epoch, pin_est
from limn.pins.mentions import addressed_to, fyi_mentions_to
from limn.pins.model import OpenPin, StateName, TrashedPin, parse_pin, state_of
from limn.pins.needs import FollowElement
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


def public_record(r: Row, place: tuple[str, str] | None) -> Json:
    """A record as the API returns it (docs/handbook/api.md §핀 파일의 위치, ADR-0006): a copy with rev defaulted to 0
    (a missing or non-integer rev) and without the stored `file_rel` and any stored `rel_path`. place is where the
    composition root finds a line pin's file under the manuscript root now - (absolute path, path relative to the
    root) - and becomes `file` and `rel_path`; with None (a region pin, or a file it cannot locate) the stored file
    stays and there is no rel_path. rel_path is always this server's answer, never a value an older version left
    behind. The API never carries a NaN, an Infinity or an integer no float holds (the store keeps them in a
    hand-edited or legacy line): a `frac` or `el.frac` with any such entry is None as a whole (a mark drawn from the
    finite entries would sit at a made-up position; limn.pins.element.element_of and the viewer skip such a frac
    too), and every other stored number - synced_at, score, claim_until, claim_ts, eta_ts, and any number inside an
    anchor, a thread entry or a field this version does not know - is None. The stored line is not touched. Never
    changes r."""
    out = dict(r)
    out["rev"] = out["rev"] if is_int(out.get("rev")) else 0
    out.pop("file_rel", None)
    out.pop("rel_path", None)
    if place is not None:
        out["file"], out["rel_path"] = place
    if "frac" in out:
        out["frac"] = _wire_frac(out["frac"])
    el = out.get("el")
    if isinstance(el, dict) and "frac" in el:
        out["el"] = {**el, "frac": _wire_frac(el["frac"])}
    return {k: wire_value(v) for k, v in out.items()}


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
    r: Row, shown: Json, rel: list[Json], est: bool, doc: str, now: float, fmap: FollowElement | None = None
) -> Json:
    """One GET /api/pins record: shown (r as the API shows it) followed by rel, est, doc, state, addressed and fyi, in
    that order, then - for a figure pin with an element on fmap, its document's current map - mark, mark_page and
    el_sync (element_marks). A claim that holds at epoch now but was written before claim_ts existed also gets
    claim_ts, its start epoch read from claimed_at (the viewer's "since 20:02 (23 min in)"); none when claimed_at is
    not a readable time. Never changes r or shown."""
    pin = parse_pin(r)
    rec = dict(shown, rel=rel, est=est, doc=doc, state=pin.state, addressed=addressed_to(pin), fyi=fyi_mentions_to(pin))
    rec.update(element_marks(r, fmap))
    if claim_holds(r, now) and not is_num(r.get("claim_ts")):
        ts = epoch(r.get("claimed_at"))
        if ts is not None:
            rec["claim_ts"] = ts
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
) -> list[Json]:
    """GET /api/pins: the open pins of rows in row order (every pin when allp), each as pin_view() gives it.

    rel is the overlaps of all rows (limn.pins.location.position.overlaps_by_id; a listed pin without an entry has []).
    doc_of names a pin's document and est_context gives the estimation facts of a document by key, or None when the
    instance no longer serves it - then est is True (placed on a PDF that is not on screen). est_context is asked
    once per document, and only for documents with a listed pin, since it reads that document's build history.
    figure_map binds a build-owned element-position query by document key, never a parsed map;
    it is asked at most once per document, and only for a document with a listed pin that carries an el."""
    ctxs: dict[str, EstContext | None] = {}
    maps: dict[str, FollowElement | None] = {}
    out = []
    for r in rows:
        if not (allp or state_of(r) is OpenPin):
            continue
        k = doc_of(r)
        if k not in ctxs:
            ctxs[k] = est_context(k)
        ctx = ctxs[k]
        fmap = None
        if element_of(r.get("el")) is not None:
            if k not in maps:
                maps[k] = figure_map(k)
            fmap = maps[k]
        est = pin_est(r, ctx) if ctx is not None else True
        out.append(pin_view(r, show(r), rel.get(r["id"], []), est, k, now, fmap))
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

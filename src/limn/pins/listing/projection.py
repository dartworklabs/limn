"""How the API shows stored pins: the computed fields of GET /api/pins and the Trash list (docs/handbook/api.md).

GET /api/pins returns each stored record plus fields computed on every read and never stored: `state` (the name of
the pin's state type), `rel` (its overlaps with other open line pins), `est` (whether its mark is only an estimate on
the PDF on screen), `doc`, `addressed` and `fyi` (who it is handed to or tags for reference), and for a claim written
before claim_ts existed the claim's start epoch - and, for a figure pin with an element, `mark`, `mark_page` and
`el_sync` on its document's current map (docs/handbook/api.md §핀 읽기). GET /api/pins/dropped returns the Trash with
`expires_ts`. Both answers are the agent contract: field names, order and values must not change.

Everything here is pure. What only the instance knows arrives as arguments: how a record is shown (the composition
root's public(): public_record() with where the pin's file is on this machine now), which document a pin belongs to,
the estimation facts
of a document's builds (read at most once per document, only for documents with a listed pin), a figure document's
current map (asked at most once per document, only for one with a listed pin that carries an element), the overlaps
already computed over all rows, when a Trash entry expires, and the clock.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TypeAlias

from limn.builds import FigureMap, Frac, follow_element
from limn.pins.element import element_of
from limn.pins.location.position import EstContext, epoch, pin_est
from limn.pins.mentions import addressed_to, fyi_mentions_to
from limn.pins.model import OpenPin, StateName, TrashedPin, parse_pin, state_of
from limn.pins.thread import claim_holds
from limn.platform.values import is_finite_num, is_int, is_num

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
    behind. A non-finite number of `frac` or of `el.frac` (NaN, an Infinity, an integer no float holds: shapes the
    store keeps in a hand-edited or legacy line) is None, number by number, so the body is strict JSON; the stored
    line is not touched. Never changes r."""
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
    return out


def _wire_frac(frac: object) -> object:
    """A stored frac as the wire can carry it: a list with each non-finite number replaced by None (a copy), anything
    else - a string, a missing value, a record the store keeps as it is - unchanged. Finite numbers, 0.0 and 1.0
    included, pass exactly."""
    if not isinstance(frac, list):
        return frac
    return [v if not is_num(v) or is_finite_num(v) else None for v in frac]


# The box compared with when neither the element nor the pin recorded one: no element's box has zero size, so it is
# never "ok".
NO_FRAC: Frac = (0.0, 0.0, 0.0, 0.0)


def no_figure_maps(key: str) -> None:
    """The figure_map of an instance without figure documents: no document has a map."""
    return None


def element_marks(r: Row, fmap: FigureMap | None) -> Json:
    """The read-time position of pin r's element on its figure document's current map: {} unless r carries a well-formed
    el (limn.pins.element) and fmap is that map; else el_sync (limn.builds.figure_map.follow_element) and, when the element is on
    the map, mark ([x, y, w, h]) and mark_page before it. Where the element was when pinned is el.frac (its box then);
    a pin without it is compared by its own frac, and a pin with neither by NO_FRAC, so it is never "ok". The page is
    the pin's page. Never stored; never changes r."""
    el = element_of(r.get("el"))
    if el is None or fmap is None:
        return {}
    frac = r.get("frac")
    then = el.frac
    if then is None and isinstance(frac, list) and len(frac) == 4 and all(is_finite_num(v) for v in frac):
        then = (float(frac[0]), float(frac[1]), float(frac[2]), float(frac[3]))
    page = r.get("page")
    got = follow_element(fmap, el.id, page if is_int(page) else 0, then or NO_FRAC)
    if got.page is None or got.frac is None:
        return {"el_sync": got.sync}
    return {"mark": list(got.frac), "mark_page": got.page, "el_sync": got.sync}


def pin_view(
    r: Row, shown: Json, rel: list[Json], est: bool, doc: str, now: float, fmap: FigureMap | None = None
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
    figure_map: Callable[[str], FigureMap | None] = no_figure_maps,
) -> list[Json]:
    """GET /api/pins: the open pins of rows in row order (every pin when allp), each as pin_view() gives it.

    rel is the overlaps of all rows (limn.pins.location.position.overlaps_by_id; a listed pin without an entry has []).
    doc_of names a pin's document and est_context gives the estimation facts of a document by key, or None when the
    instance no longer serves it - then est is True (placed on a PDF that is not on screen). est_context is asked
    once per document, and only for documents with a listed pin, since it reads that document's build history.
    figure_map gives a figure document's current map by key (None for another document or one that does not load);
    it is asked at most once per document, and only for a document with a listed pin that carries an el."""
    ctxs: dict[str, EstContext | None] = {}
    maps: dict[str, FigureMap | None] = {}
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

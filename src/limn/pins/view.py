"""How the API shows stored pins: the computed fields of GET /api/pins and the Trash list (docs/handbook/api.md).

GET /api/pins returns each stored record plus fields computed on every read and never stored: `state` (the name of
the pin's state type), `rel` (its overlaps with other open line pins), `est` (whether its mark is only an estimate on
the PDF on screen), `doc`, `addressed` and `fyi` (who it is handed to or tags for reference), and for a claim written
before claim_ts existed the claim's start epoch. GET /api/pins/dropped returns the Trash with `expires_ts`. Both
answers are the agent contract: field names, order and values must not change.

Everything here is pure. What only the instance knows arrives as arguments: how a record is shown (the composition
root's public(): public_record() with where the pin's file is on this machine now), which document a pin belongs to,
the estimation facts
of a document's builds (read at most once per document, only for documents with a listed pin), the overlaps already
computed over all rows, when a Trash entry expires, and the clock.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TypeAlias

from limn.mentions import addressed_to, fyi_mentions_to
from limn.pins.lifecycle import claim_holds
from limn.pins.model import StateName, state_of
from limn.pins.position import EstContext, epoch, pin_est

# One stored pin (or Trash entry) as the store read it, and one record as the API returns it: JSON objects.
Row: TypeAlias = Mapping[str, Any]
Json: TypeAlias = dict[str, Any]
# How the API shows a record before the computed fields: a copy placed on this machine (server.public()).
Show: TypeAlias = Callable[[Row], Json]


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
    behind. Never changes r."""
    out = dict(r)
    out["rev"] = out["rev"] if _is_int(out.get("rev")) else 0
    out.pop("file_rel", None)
    out.pop("rel_path", None)
    if place is not None:
        out["file"], out["rel_path"] = place
    return out


def _is_int(v: object) -> bool:
    """An int that is not a bool - how a stored rev is recognised."""
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: object) -> bool:
    """A JSON number (int or float, not bool) - how a stored claim_ts is recognised."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def pin_view(r: Row, shown: Json, rel: list[Json], est: bool, doc: str, now: float) -> Json:
    """One GET /api/pins record: shown (r as the API shows it) followed by rel, est, doc, state, addressed and fyi, in
    that order. A claim that holds at epoch now but was written before claim_ts existed also gets claim_ts, its start
    epoch read from claimed_at (the viewer's "since 20:02 (23 min in)"); none when claimed_at is not a readable time.
    Never changes r or shown."""
    rec = dict(shown, rel=rel, est=est, doc=doc, state=pin_state(r), addressed=addressed_to(r), fyi=fyi_mentions_to(r))
    if claim_holds(r, now) and not _is_num(r.get("claim_ts")):
        ts = epoch(r.get("claimed_at"))
        if ts is not None:
            rec["claim_ts"] = ts
    return rec


def pins_payload(rows: Sequence[Row], allp: bool, rel: Mapping[int, list[Json]], show: Show,
                 doc_of: Callable[[Row], str], est_context: Callable[[str], EstContext | None],
                 now: float) -> list[Json]:
    """GET /api/pins: the open pins of rows in row order (every pin when allp), each as pin_view() gives it.

    rel is the overlaps of all rows (limn.pins.position.overlaps_by_id; a listed pin without an entry has []).
    doc_of names a pin's document and est_context gives the estimation facts of a document by key, or None when the
    instance no longer serves it - then est is True (placed on a PDF that is not on screen). est_context is asked
    once per document, and only for documents with a listed pin, since it reads that document's build history."""
    ctxs: dict[str, EstContext | None] = {}
    out = []
    for r in rows:
        if not (allp or not r.get("done")):
            continue
        k = doc_of(r)
        if k not in ctxs:
            ctxs[k] = est_context(k)
        ctx = ctxs[k]
        out.append(pin_view(r, show(r), rel.get(r["id"], []), pin_est(r, ctx) if ctx is not None else True, k, now))
    return out


def dropped_payload(rows: Iterable[Row], show: Show, expires_ts: Callable[[Row], float | None]) -> list[Json]:
    """GET /api/pins/dropped: the Trash entries rows (already without expired ones) ordered by dropped_at, each as show
    gives it plus `expires_ts` - when it leaves the Trash, rounded to milliseconds, for the viewer's "gone in N days"
    free of the browser's time zone - when expires_ts knows it. The order of entries with the same or no dropped_at
    is rows' order."""
    out = []
    for r in sorted(rows, key=lambda r: str(r.get("dropped_at") or "")):
        rec, exp = show(r), expires_ts(r)
        if exp is not None:
            rec["expires_ts"] = round(exp, 3)
        out.append(rec)
    return out

"""Where a stored pin stands against the manuscript now - the pure rules of its position (docs/handbook/domain.md).

Three rules, each a computation over values the caller has already read:

- **Location estimation (`est`)** - whether a pin's mark may no longer match the PDF on screen (pin_est). Judged by
  build identity: the build the pin was placed on (pdf_build) against the current build, and whether the two came from
  the same manuscript. The wall clock is never read; the facts arrive as an EstContext (est_basis).
- **Overlap** - how open line pins of one file relate to each other (overlaps_by_id) and to a not-yet-saved
  selection (selection_rel, overlaps_for_range). Computed on every read, never stored.
- **Anchor re-sync** - where a pin's lines are after the manuscript was edited (follow_anchor), and the record that
  results (resync).

Nothing here reads files, the clock, subprocesses or HTTP (coding rule R1). Reading the .tex files, the build history
and where a pin's file is now is limn.locate's job; it passes the facts in and applies what comes back.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeAlias, TypeGuard

from limn.mapping import anchor_holds, anchor_of, anchor_offset, find_line
from limn.pins.lifecycle import next_rev

# One stored pin as the store holds it: a JSON object. The rules here only read it; resync returns a changed copy.
Row: TypeAlias = Mapping[str, Any]
# How one range relates to another: a lies inside b, a contains b, or they overlap in part.
RangeRel: TypeAlias = Literal["inside", "contains", "partial"]


def _is_num(v: object) -> TypeGuard[int | float]:
    """A JSON number (int or float, not bool) - how a stored src_mtime is recognised."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------- Location estimation (.est)
#
# A mark is fixed to frac (the ratio relative to the page) at the moment the pin was placed. If those coordinates might
# no longer match the PDF currently on screen, it's "estimated" (dashed). The judgment is made by build identity:
# estimated if the build the pin was placed on screen with (pdf_build) differs from the current build and the two
# builds' manuscript fingerprints differ. Also estimated if anchor line matching moved or lost the pin. The wall clock
# is never used - browser timezone, a note-only edited_at, and a pin placed on a stale PDF were all wrong across the
# board.

def epoch(s: object) -> float | None:
    """A stored time -> epoch seconds, or None when s is not a readable time.

    Accepts 'YYYY-MM-DD HH:MM:SS' (server local time, the shape now_str writes) and ISO 8601 with an offset. A time
    without an offset is read in this process's local time zone - it was written by this server, on this machine."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace(" ", "T", 1))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()          # this value was written in server local time - read back on the same machine
    return dt.timestamp()


def pin_build(r: Row) -> str | None:
    """The name of the build a pin's coordinates belong to, or None for a pin that never recorded one. frac_build is
    the legacy field name with the same meaning (83b91a5)."""
    for k in ("pdf_build", "frac_build"):
        v = r.get(k)
        if isinstance(v, str) and v:
            return v
    return None


@dataclass(frozen=True)
class EstContext:
    """What estimation needs to know about one document's builds, read once per request (limn.locate.est_context).

    cur is the build on screen; by maps a build name to its history entry (builds.json, with an entry for cur even
    before the history has one); built_at is when the current build finished and built_src_mtime the manuscript's
    mtime when it started (both epoch seconds, None when unknown)."""
    cur: str
    by: Mapping[str, Mapping[str, Any]]
    built_at: float | None
    built_src_mtime: float | None


def est_basis(cur: str, history: Mapping[str, Mapping[str, Any]], built_src_mtime: float | None,
              built_at: float | None) -> EstContext:
    """The EstContext of a document from what was read of it: the current build's name, the build history by name,
    the current build's recorded manuscript mtime (None if not recorded) and its finish time.

    A current build missing from the history (before seed_builds(), or a rare race) is judged with what is known: an
    entry with the recorded mtime and no hash. Without a recorded mtime, the history entry's src_mtime is used."""
    by = dict(history)
    if cur not in by:
        by[cur] = {"build": cur, "src_mtime": built_src_mtime, "src_hash": None}
    bsm = built_src_mtime
    if bsm is None and _is_num(by[cur].get("src_mtime")):
        bsm = float(by[cur]["src_mtime"])
    return EstContext(cur, by, built_at, bsm)


def same_source(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> bool:
    """Were two builds made from the same manuscript? By hash if both have one, otherwise by src_mtime at start.
    False (treated as different) if neither is known - rendering it as "exact location" while actually unsure would
    be worse."""
    if not a or not b:
        return False
    if a.get("src_hash") and b.get("src_hash"):
        return bool(a["src_hash"] == b["src_hash"])
    ma, mb = a.get("src_mtime"), b.get("src_mtime")
    return _is_num(ma) and _is_num(mb) and abs(float(ma) - float(mb)) < 0.01


def legacy_est(r: Row, ctx: EstContext) -> bool:
    """Fallback heuristic for a legacy pin without pdf_build (the old viewer's rule, redone server-side with epoch
    numbers): estimated if the pin was placed before the current PDF, and the manuscript that produced the current PDF
    (src_mtime at start) changed after the pin.

    The only reference time is when it was placed (at) - using edited_at would turn off estimation just from
    editing the note (confirmed by independent verification). An edit that re-places frac (loc) now records
    pdf_build, so it no longer falls through to this heuristic."""
    ba, pa = ctx.built_at, epoch(r.get("at"))
    if ba is None or pa is None or pa >= ba:
        return False
    return ctx.built_src_mtime is not None and ctx.built_src_mtime > pa


def pin_est(r: Row, ctx: EstContext) -> bool:
    """Is pin r's mark only an estimate on the current PDF? True when its anchor moved or was lost (stale, or a sync
    other than "ok"); otherwise by build identity (pdf_build against ctx.cur and same_source), or legacy_est for a pin
    that recorded no build."""
    sync = r.get("sync")
    if r.get("stale") or (isinstance(sync, str) and sync != "ok"):
        return True                                   # moved +-N / lost - the anchor shifted or was lost
    b = pin_build(r)
    if b is None:
        return legacy_est(r, ctx)
    if b == ctx.cur:
        return False
    return not same_source(ctx.by.get(b), ctx.by.get(ctx.cur))


# ---------------------------------------------------------------- Overlap - a computed field, never stored

def range_rel(a_lo: int, a_hi: int, b_lo: int, b_hi: int) -> RangeRel | None:
    """a's relationship to b (inclusive line ranges). None if they don't overlap; two equal ranges are "contains"."""
    if a_hi < b_lo or b_hi < a_lo:
        return None
    if b_lo <= a_lo and a_hi <= b_hi:
        return "contains" if (a_lo, a_hi) == (b_lo, b_hi) else "inside"
    if a_lo <= b_lo and b_hi <= a_hi:
        return "contains"
    return "partial"


def overlaps_by_id(rows: Sequence[Row], file_of: Callable[[Row], str]) -> dict[int, list[dict[str, Any]]]:
    """The relationship of every pair of open line pins on the same file (never stored): {id: [{"id", "rel"}, ...]},
    with an entry (possibly empty) for every open pin, in row order.

    file_of(r) names the file an open line pin is counted in - the caller's located path, so pins made before and
    after a move of the checkout are one file; it is called once per open line pin, in row order. When two ranges
    are exactly equal, the one with the smaller id is treated as the outer one (contains) - since neither is truly
    nested inside the other, a single deterministic rule is needed."""
    out: dict[int, list[dict[str, Any]]] = {}
    by_file: dict[str, list[Row]] = {}
    for r in rows:
        if r.get("done"):
            continue
        out.setdefault(r["id"], [])
        if not r.get("file"):                          # a view-only PDF's pin - no line-range overlap
            continue
        by_file.setdefault(file_of(r), []).append(r)
    for group in by_file.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if (a["lo"], a["hi"]) == (b["lo"], b["hi"]):
                    outer, inner = (a, b) if a["id"] < b["id"] else (b, a)
                    out[inner["id"]].append({"id": outer["id"], "rel": "inside"})
                    out[outer["id"]].append({"id": inner["id"], "rel": "contains"})
                    continue
                rel_a = range_rel(a["lo"], a["hi"], b["lo"], b["hi"])   # does a fall inside b?
                if rel_a == "inside":
                    out[a["id"]].append({"id": b["id"], "rel": "inside"})
                    out[b["id"]].append({"id": a["id"], "rel": "contains"})
                elif rel_a == "contains":
                    out[a["id"]].append({"id": b["id"], "rel": "contains"})
                    out[b["id"]].append({"id": a["id"], "rel": "inside"})
                elif rel_a == "partial":
                    out[a["id"]].append({"id": b["id"], "rel": "partial"})
                    out[b["id"]].append({"id": a["id"], "rel": "partial"})
    return out


def selection_rel(lo: int, hi: int, b_lo: int, b_hi: int) -> Literal["equal"] | RangeRel | None:
    """The relationship between a not-yet-saved selection (lo..hi) and a saved pin (b_lo..b_hi) - from the
    selection's point of view.

    equal (same range - the most common duplicate: placing a pin on the same paragraph/environment twice) -
    inside (selection is inside the pin) - contains (selection wraps the pin) - partial (overlapping) -
    None (no overlap). Same rule as the viewer's overlapsFor() (the browser recomputes this on every range
    change without a server round trip - a regression test compares the two implementations)."""
    if (lo, hi) == (b_lo, b_hi):
        return "equal"
    return range_rel(lo, hi, b_lo, b_hi)


def overlaps_for_range(file: str, lo: int, hi: int, rows: Sequence[Row],
                       file_of: Callable[[Row], str]) -> list[dict[str, Any]]:
    """The overlap relationships between a not-yet-saved range lo..hi of file and the open line pins of rows counted
    in that file (file_of, as in overlaps_by_id): [{"id", "lo", "hi", "rel"}] in row order. Nothing is saved.

    Between saved pins (overlaps_by_id), equal ranges are split into inner/outer by id, but a new selection
    has no id yet, so an identical range is reported separately as 'equal' - the viewer surfaces all four
    relationships via a banner with wording that spells out the relationship."""
    out = []
    for r in rows:
        if r.get("done") or not r.get("file"):
            continue
        if file_of(r) != file:
            continue
        rel = selection_rel(lo, hi, r["lo"], r["hi"])
        if rel:
            out.append({"id": r["id"], "lo": r["lo"], "hi": r["hi"], "rel": rel})
    return out


# ---------------------------------------------------------------- Anchors and re-syncing

@dataclass(frozen=True)
class Followed:
    """The anchor was found: the pin's lines are now lo..hi, and sync says how far they moved ("ok" or "moved +N")."""
    lo: int
    hi: int
    sync: str


@dataclass(frozen=True)
class AnchorLost:
    """The anchor's head line is no longer near the pin: its lines cannot be followed (stale, sync "lost")."""


def follow_anchor(anchor: Mapping[str, Any], lo: int, hi: int, nlines: Sequence[str]) -> Followed | AnchorLost:
    """Where a pin recorded at lo..hi with anchor is in the file whose normalised lines are nlines.

    The head line is looked up near where it was (lo plus its offset); the tail near where it would be after the same
    shift. A tail found before the head keeps the old span. The result is clamped to the file (1..len)."""
    ho, to = anchor_offset(anchor.get("head_off")), anchor_offset(anchor.get("tail_off"))   # 0 for a legacy anchor
    span = hi - lo
    head = find_line(nlines, anchor.get("head", ""), lo + ho)
    if head is None:
        return AnchorLost()
    n = max(1, len(nlines))
    new_lo = max(1, head - ho)
    tail = find_line(nlines, anchor.get("tail", ""), hi - to + (new_lo - lo))
    new_hi = tail + to if tail is not None and tail >= head else new_lo + span
    new_hi = max(new_lo, min(n, new_hi))
    return Followed(new_lo, new_hi, "ok" if (new_lo, new_hi) == (lo, hi) else "moved %+d" % (new_lo - lo))


def resync(r: Row, lines: Sequence[str], nlines: Sequence[str], mtime: float, path: str) -> dict[str, Any] | None:
    """Open line pin r re-matched against its file as read now - the file at path (where the pin's file is found
    today, ADR-0006), its lines, their normalised form nlines and its mtime. Returns the changed record (a copy, keys
    in the stored order) or None when nothing changes.

    - A legacy pin saved without an anchor gets one from its current lines, once - never from a file the record does
      not name (path differs from the stored file: it may be a guess).
    - A pin that selected only blank lines (empty anchor) has nothing to follow.
    - When the file is not newer than synced_at the pin is left alone - unless path is another file than the stored
      one (a moved checkout: synced_at was measured on the old file) and the anchor no longer holds at lo.
    - Otherwise its lines follow the anchor (follow_anchor): moved lines or a lost anchor bump rev; a re-match on a
      moved record writes path into `file`, so lines, synced_at and file describe one file again. `file_rel` is never
      added here."""
    moved = path != r["file"]                    # measured on another file than the stored one (ADR-0006)
    if "anchor" not in r:                        # backfill a legacy pin saved without an anchor, once
        if moved:
            return None                          # never from a file the record does not name (it may be a guess)
        out = dict(r)
        out["anchor"] = anchor_of(lines, r["lo"], r["hi"])
        out["synced_at"] = mtime
        return out
    if not r["anchor"]:                          # a pin that selected only blank lines has no anchor to follow
        return None
    if r.get("synced_at", 0) >= mtime and (not moved or anchor_holds(r["anchor"], r["lo"], nlines)):
        return None
    out = dict(r)
    before = (r["lo"], r["hi"], bool(r.get("stale")))
    match follow_anchor(r["anchor"], r["lo"], r["hi"], nlines):
        case AnchorLost():
            out["stale"], out["sync"] = True, "lost"
        case Followed(lo=lo, hi=hi, sync=sync):
            out["sync"] = sync
            out["lo"], out["hi"] = lo, hi
            out.pop("stale", None)
    if (out["lo"], out["hi"], bool(out.get("stale"))) != before:
        out["rev"] = next_rev(out)
    if moved:
        out["file"] = path                       # the new numbers describe this file
    out["synced_at"] = mtime
    return out

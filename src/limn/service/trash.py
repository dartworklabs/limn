"""The Trash (pins.dropped.jsonl) and clear (docs/handbook/domain.md §전이와 할 수 있는 쪽, docs/handbook/api.md §휴지통).

A dropped pin stays restorable for trash_days, counted from dropped_at (local time, like every *_at string). Reading
never writes: GET /api/pins/dropped only hides expired entries; the file is rewritten without them at startup, on
every drop/restore, and by the owner's permanent delete. An entry without a readable dropped_at is kept - its age
cannot be known, and guessing would delete data. ids stay reserved in pins.seq, so a purged number is never reused.

Every write of the Trash happens under the pin store's lock. The irreversible operations (purge, clear) leave a
notice, an audit.jsonl line and a log line; the audit line is appended outside the lock (it flocks and fsyncs).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from typing import Any

from limn.access import LOCAL_ACTOR
from limn.pins.lifecycle import AlreadyLive, NotInTrash, drop, find_trashed, restore
from limn.pins.model import DonePin, OpenPin, PinNotFound, ReviewPin, TrashedPin, parse_pin
from limn.pins.position import epoch as parse_epoch
from limn.service.context import Event, Json, PinContext, Row, typed_actor
from limn.store import find_pin

# a long-running server also drops expired Trash entries during normal reads, at most this often
TRASH_CHECK_EVERY_S = 3600


def expires_ts(r: Mapping[str, Any], days: int) -> float | None:
    """Epoch seconds at which a Trash entry expires (dropped_at + days), or None if dropped_at is unreadable."""
    t = parse_epoch(r.get("dropped_at"))
    return None if t is None else t + days * 86400


def expired(r: Mapping[str, Any], days: int, now: float) -> bool:
    """Is Trash entry r past its expiry at epoch now? An entry whose age cannot be read never expires."""
    t = expires_ts(r, days)
    return t is not None and now > t


def unexpired(rows: Sequence[Row], days: int, now: float) -> list[Row]:
    """The Trash entries still restorable at epoch now, in their order."""
    return [r for r in rows if not expired(r, days, now)]


def _live_trash(ctx: PinContext, rows: Sequence[Row], now: float | None = None) -> list[Row]:
    """The entries of rows unexpired at now, or - when now is None - at the clock read now."""
    return unexpired(rows, ctx.trash_days, ctx.epoch() if now is None else now)


def drop_pin(ctx: PinContext, pid: int, actor: Mapping[str, Any]) -> TrashedPin | PinNotFound:
    """Removes a pin from pins.jsonl and moves it to the Trash (pins.dropped.jsonl). restore brings the same id back.

    The author is told when someone else deletes their pin (a `dropped` event, with [Restore] in the viewer). Expired
    Trash entries are purged in the same write."""
    evs: list[Event | None] = []

    def fn(rows: list[Row]) -> tuple[TrashedPin | PinNotFound, bool]:
        """The transact() step: take pin pid out of rows, append it to the Trash and queue its `dropped` notice."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        rows.remove(r)
        trashed = drop(parse_pin(r), typed_actor(actor), ctx.now())
        old, bad = ctx.store.read_dropped()
        ctx.store.write_dropped(_live_trash(ctx, old) + [dict(trashed.record)], bad)
        evs.append(ctx.make_event("dropped", r, actor, [(r.get("author") or {}).get("login")], text=r.get("note")))
        return trashed, True

    with ctx.store.lock:
        out = ctx.store.transact(fn)[1]
        ctx.emit_events(evs)
    return out


def restore_pin(
    ctx: PinContext, pid: int, actor: Mapping[str, Any]
) -> OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive:
    """Writes to pins.jsonl first, and only removes it from the dropped record once that succeeds.

    Reversing the order means a crash between the two writes makes the pin vanish from both files (observed).
    With this order, the worst case is "present in both", which is recoverable."""
    with ctx.store.lock:  # re-entrant - bundles transact and cleaning up the dropped record
        result = ctx.store.transact(lambda rows: _restore(ctx, rows, pid, actor))[1]
        if isinstance(result, (NotInTrash, AlreadyLive)):
            return result  # refused: the Trash file is left as it was
        old, bad = ctx.store.read_dropped()
        ctx.store.write_dropped(_live_trash(ctx, [r for r in old if r.get("id") != pid]), bad)
        return result


def _restore(
    ctx: PinContext, rows: list[Row], pid: int, actor: Mapping[str, Any]
) -> tuple[OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive, bool]:
    """The transact() step of restore_pin: puts the newest unexpired Trash copy of pin pid back into rows, re-synced and
    with rel_path and the current file recorded (ADR-0006). The rule is limn.pins.lifecycle.restore(); NotInTrash
    (404) and AlreadyLive (409) leave rows unchanged."""
    old, _ = ctx.store.read_dropped()
    trashed = find_trashed(_live_trash(ctx, old), pid)
    if isinstance(trashed, NotInTrash):
        return trashed, False
    result = restore(trashed, find_pin(rows, pid) is not None, typed_actor(actor), ctx.now())
    if isinstance(result, AlreadyLive):
        return result, False
    rec = dict(result.record)
    ctx.store.sync([rec])
    ctx.stamp(rec)  # ADR-0006: a restored pin records where its file is now
    rows.append(rec)
    rows.sort(key=lambda r: r["id"])
    return parse_pin(rec), True


def purge_trash(ctx: PinContext, now: float | None = None) -> int:
    """Rewrites pins.dropped.jsonl without the entries older than trash_days. Returns how many went (0 = no write, or
    the write failed - reads hide expired entries anyway, so a failure is only a warning). now defaults to the clock;
    every check (startup, drop, restore) restarts the hourly clock of maybe_purge_trash."""
    ctx.trash_checked[0] = ctx.epoch() if now is None else now
    with ctx.store.lock:
        rows, bad = ctx.store.read_dropped()
        keep = _live_trash(ctx, rows, now)
        n = len(rows) - len(keep)
        if n:
            try:
                ctx.store.write_dropped(keep, bad)
            except OSError as e:  # e.g. a read-only state dir: expired entries stay hidden, the server still starts
                print("warning: could not purge the Trash: %s" % e, file=sys.stderr)
                return 0
    if n:
        print("trash: purged %d pin(s) deleted more than %d days ago" % (n, ctx.trash_days), file=sys.stderr)
        sys.stderr.flush()
    return n


def maybe_purge_trash(ctx: PinContext) -> int:
    """The lazy expiry: called from the reads that already write (GET /api/pins, /pins.md - they re-sync line numbers),
    never from the write-free light poll. One cheap clock comparison; at most once per TRASH_CHECK_EVERY_S it reads the
    Trash and rewrites it only if something expired."""
    now = ctx.epoch()
    if now - ctx.trash_checked[0] < TRASH_CHECK_EVERY_S:
        return 0
    ctx.trash_checked[0] = now
    return purge_trash(ctx, now)


def purge_pin(ctx: PinContext, pid: int, actor: Mapping[str, Any]) -> TrashedPin | NotInTrash:
    """The owner's permanent delete from the Trash (POST /api/pins/{id}/purge; check_role refuses everyone else).
    Returns the purged entry, or NotInTrash (nothing written) if the pin is not in the Trash - an open or closed pin
    must be dropped first; the handler answers that with 404. Leaves a `purged` audit event (to: [], like `cleared`), a
    `purged` line in audit.jsonl (v0.3.1, never rotated out) and a log line, since it cannot be undone."""
    with ctx.store.lock:
        rows, bad = ctx.store.read_dropped()
        found = find_trashed(_live_trash(ctx, rows), pid)
        if isinstance(found, NotInTrash):
            return found
        ctx.store.write_dropped(_live_trash(ctx, [r for r in rows if r.get("id") != pid]), bad)
        ctx.emit_events([{"type": "purged", "to": [], "pin": pid, "by": ctx.who(actor)}])
    ctx.audit("purged", ctx.who(actor), {"pin": pid})  # outside the lock: it flocks and fsyncs
    print("trash: pin #%d deleted permanently by %s" % (pid, (actor or {}).get("login")), file=sys.stderr)
    sys.stderr.flush()
    return found


def clear_pins(ctx: PinContext, actor: Mapping[str, Any] | None = None) -> Json:
    """Archives everything to pins_<ts>.jsonl.bak and clears it. pins.seq is untouched, so ids keep incrementing.
    Records a `cleared` event (who, how many, which archive), a `cleared` line in audit.jsonl (v0.3.1 - the event can
    rotate out of events.jsonl, the audit line does not) and a log line - the only bulk-destructive operation, so it
    always leaves a trace. No actor means the headerless agent. Returns {"cleared": n, "archive": <file name or None>}."""
    by = ctx.who(actor or LOCAL_ACTOR)
    with ctx.store.lock:
        n, archive = ctx.store.clear()  # never over an earlier archive of the same second
        ctx.emit_events([{"type": "cleared", "to": [], "by": by, "n": n, "archive": archive}])
    ctx.audit("cleared", by, {"n": n, "archive": archive})  # outside the lock: it flocks and fsyncs
    print(
        "clear: %d pin(s) archived to %s by %s" % (n, archive or "-", (actor or LOCAL_ACTOR).get("login")),
        file=sys.stderr,
    )
    sys.stderr.flush()
    return {"cleared": n, "archive": archive}

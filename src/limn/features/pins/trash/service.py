"""The Trash (pins.dropped.jsonl) and clear (docs/handbook/domain.md §전이와 할 수 있는 쪽, docs/handbook/api.md §휴지통).

A dropped pin stays restorable for trash_days, counted from dropped_at (local time, like every *_at string). Reading
never writes: GET /api/pins/dropped hides expired entries and copies of live pins; the file is pruned at startup,
hourly on reads that already write, on drop/restore, and by the owner's permanent delete. An entry without a readable
dropped_at is kept unless its id is live - its age cannot be known, and guessing would delete data. ids stay reserved
in pins.seq, so a purged number is never reused.

Every write of the Trash happens under the pin store's lock. The irreversible operations (purge, clear) leave a
notice, an audit.jsonl line and a log line; the audit line is appended outside the lock (it flocks and fsyncs).
"""

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from limn.access import LOCAL_ACTOR
from limn.pins.lifecycle import AlreadyLive, NotInTrash, drop, find_trashed, restore
from limn.pins.model import DonePin, OpenPin, Pin, PinNotFound, ReviewPin, TrashedPin, parse_pin
from limn.pins.trash import unexpired, without_live_shadows
from limn.service.context import Event, Json, PinContext, load_pin, typed_actor
from limn.store import pin_index

# a long-running server also drops expired Trash entries during normal reads, at most this often
TRASH_CHECK_EVERY_S = 3600


def _live_trash(ctx: PinContext, entries: Sequence[TrashedPin], now: float | None = None) -> list[TrashedPin]:
    """The entries unexpired at now, or - when now is None - at the clock read now."""
    return unexpired(entries, ctx.trash_days, ctx.epoch() if now is None else now)


def _without(entries: Sequence[TrashedPin], pid: int) -> list[TrashedPin]:
    """The Trash entries that are not a copy of pin pid, in their order."""
    return [entry for entry in entries if entry.pin.core.id != pid]


def drop_pin(ctx: PinContext, pid: int, actor: Mapping[str, Any]) -> TrashedPin | PinNotFound:
    """Removes a pin from pins.jsonl and moves it to the Trash (pins.dropped.jsonl). restore brings the same id back.

    The author is told when someone else deletes their pin (a `dropped` event, with [Restore] in the viewer). Expired
    Trash entries are purged in the same write."""
    evs: list[Event | None] = []

    def fn(pins: list[Pin]) -> tuple[TrashedPin | PinNotFound, bool]:
        """Remove pid in memory and queue its notice; the Trash write follows preparation of the live bytes."""
        found = load_pin(pins, pid)
        if isinstance(found, PinNotFound):
            return found, False
        i, pin = found
        del pins[i]
        trashed = drop(pin, typed_actor(actor), ctx.now())
        r = pin.record
        evs.append(ctx.make_event("dropped", r, actor, [(pin.core.author or {}).get("login")], text=r.get("note")))
        return trashed, True

    def write_trash(result: TrashedPin | PinNotFound) -> None:
        """Replace the target's Trash row after live rendering succeeds but before the live file changes."""
        if isinstance(result, PinNotFound):
            return
        old, bad = ctx.store.read_dropped()
        ctx.store.write_dropped(_without(_live_trash(ctx, old), pid) + [result], bad)

    with ctx.store.lock:
        out = ctx.store.transact(fn, before_write=write_trash)[1]
        ctx.emit_events(evs)
    return out


def restore_pin(
    ctx: PinContext, pid: int, actor: Mapping[str, Any]
) -> OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive:
    """Writes to pins.jsonl first, then removes its Trash copy. An interrupted restore may leave both copies;
    retry returns AlreadyLive as before and removes that shadow copy."""
    with ctx.store.lock:  # re-entrant - bundles transact and cleaning up the dropped record
        result = ctx.store.transact(lambda pins: _restore(ctx, pins, pid, actor))[1]
        if isinstance(result, NotInTrash):
            return result
        old, bad = ctx.store.read_dropped()
        if isinstance(result, AlreadyLive):
            # A previous restore may have committed pins.jsonl but failed before removing its Trash copy.
            if any(entry.pin.core.id == pid for entry in old):
                ctx.store.write_dropped(_without(old, pid), bad)
            return result
        ctx.store.write_dropped(_live_trash(ctx, _without(old, pid)), bad)
        return result


def _restore(
    ctx: PinContext, pins: list[Pin], pid: int, actor: Mapping[str, Any]
) -> tuple[OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive, bool]:
    """The transact() step of restore_pin: puts the newest unexpired Trash copy of pin pid back into pins (kept in id
    order) with its file and file_rel recorded where the file is now (ADR-0006). Its lines are not re-matched here:
    the next transaction's sync does that, as for every pin. The rule is limn.pins.lifecycle.restore(); NotInTrash
    (404) and AlreadyLive (409) leave pins unchanged."""
    old, _ = ctx.store.read_dropped()
    trashed = find_trashed(_live_trash(ctx, old), pid)
    if isinstance(trashed, NotInTrash):
        return trashed, False
    result = restore(trashed, pin_index(pins, pid) is not None, typed_actor(actor), ctx.now())
    if isinstance(result, AlreadyLive):
        return result, False
    rec = dict(result.record)
    ctx.stamp(rec)  # ADR-0006: a restored pin records where its file is now
    restored = parse_pin(rec)
    pins.append(restored)
    pins.sort(key=lambda pin: pin.core.pid)
    return restored, True


def purge_trash(ctx: PinContext, now: float | None = None) -> int:
    """Prunes expired entries and copies of live pins. Returns the expired count (0 can also mean a failed write).
    now defaults to the clock; a successful check restarts the hourly clock of maybe_purge_trash."""
    checked_at = ctx.epoch() if now is None else now
    with ctx.store.lock:
        try:
            pins, _ = ctx.store.read_pins()
            entries, bad = ctx.store.read_dropped()
            visible = without_live_shadows(entries, pins)
            keep = _live_trash(ctx, visible, checked_at)
            expired_count = len(visible) - len(keep)
            shadow_count = len(entries) - len(visible)
            if len(keep) != len(entries):
                ctx.store.write_dropped(keep, bad)
        except OSError as e:  # e.g. a read-only state dir: expiry and shadows stay hidden, startup continues
            print("warning: could not purge the Trash: %s" % e, file=sys.stderr)
            return 0
        ctx.trash_checked[0] = checked_at
    if expired_count:
        print(
            "trash: purged %d pin(s) deleted more than %d days ago" % (expired_count, ctx.trash_days),
            file=sys.stderr,
        )
        sys.stderr.flush()
    if shadow_count:
        print("trash: reconciled %d live shadow(s)" % shadow_count, file=sys.stderr)
        sys.stderr.flush()
    return expired_count


def maybe_purge_trash(ctx: PinContext) -> int:
    """The lazy Trash cleanup on reads that already sync pins (GET /api/pins and /pins.md), never on the light poll.
    A successful check waits TRASH_CHECK_EVERY_S before the next; a failed read or write retries on the next such
    request. It rewrites the Trash only when entries expired or still-live pins have shadow copies."""
    now = ctx.epoch()
    if now - ctx.trash_checked[0] < TRASH_CHECK_EVERY_S:
        return 0
    return purge_trash(ctx, now)


def purge_pin(ctx: PinContext, pid: int, actor: Mapping[str, Any]) -> TrashedPin | NotInTrash:
    """The owner's permanent delete from the Trash (POST /api/pins/{id}/purge; check_role refuses everyone else).
    Returns the purged entry, or NotInTrash (nothing written) if the pin is not in the Trash - an open or closed pin
    must be dropped first; the handler answers that with 404. Leaves a `purged` audit event (to: [], like `cleared`), a
    `purged` line in audit.jsonl (never rotated out) and a log line, since it cannot be undone."""
    with ctx.store.lock:
        if pin_index(ctx.store.read_pins()[0], pid) is not None:
            return NotInTrash(pid)
        entries, bad = ctx.store.read_dropped()
        found = find_trashed(_live_trash(ctx, entries), pid)
        if isinstance(found, NotInTrash):
            return found
        ctx.store.write_dropped(_live_trash(ctx, _without(entries, pid)), bad)
        ctx.emit_events([{"type": "purged", "to": [], "pin": pid, "by": ctx.who(actor)}])
    ctx.audit("purged", ctx.who(actor), {"pin": pid})  # outside the lock: it flocks and fsyncs
    print("trash: pin #%d deleted permanently by %s" % (pid, (actor or {}).get("login")), file=sys.stderr)
    sys.stderr.flush()
    return found


def clear_pins(ctx: PinContext, actor: Mapping[str, Any] | None = None) -> Json:
    """Archives everything to pins_<ts>.jsonl.bak and clears it. pins.seq is untouched, so ids keep incrementing.
    Records a `cleared` event (who, how many, which archive), a `cleared` line in audit.jsonl (the event can rotate
    out of events.jsonl, the audit line does not) and a log line - the only bulk-destructive operation, so it
    always leaves a trace. No actor means the headerless agent. Returns {"cleared": n, "archive": <file name or None>}."""
    by = ctx.who(actor or LOCAL_ACTOR)

    def remove_shadows(pins: Sequence[Pin]) -> None:
        """Remove only verified live IDs from Trash after clear's Markdown has rendered, before its archive move."""
        entries, bad = ctx.store.read_dropped()
        keep = without_live_shadows(entries, pins)
        if len(keep) != len(entries):
            ctx.store.write_dropped(keep, bad)

    with ctx.store.lock:
        n, archive = ctx.store.clear(before_archive=remove_shadows)  # never over an earlier archive of the same second
        ctx.emit_events([{"type": "cleared", "to": [], "by": by, "n": n, "archive": archive}])
    ctx.audit("cleared", by, {"n": n, "archive": archive})  # outside the lock: it flocks and fsyncs
    print(
        "clear: %d pin(s) archived to %s by %s" % (n, archive or "-", (actor or LOCAL_ACTOR).get("login")),
        file=sys.stderr,
    )
    sys.stderr.flush()
    return {"cleared": n, "archive": archive}


@dataclass(frozen=True)
class PinTrash:
    """Trash operations bound to one application's context factory."""

    context: Callable[[], PinContext]

    def drop_pin(self, pid: int, actor: Mapping[str, Any]) -> TrashedPin | PinNotFound:
        """Move one pin to the Trash under the store lock."""
        return drop_pin(self.context(), pid, actor)

    def restore_pin(
        self, pid: int, actor: Mapping[str, Any]
    ) -> OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive:
        """Restore one Trash entry under the store lock."""
        return restore_pin(self.context(), pid, actor)

    def purge_pin(self, pid: int, actor: Mapping[str, Any]) -> TrashedPin | NotInTrash:
        """Permanently delete one Trash entry and audit it."""
        return purge_pin(self.context(), pid, actor)

    def clear_pins(self, actor: Mapping[str, Any] | None = None) -> Json:
        """Archive and clear all live pins, preserving the audit trail."""
        return clear_pins(self.context(), actor)

    def purge_trash(self, now: float | None = None) -> int:
        """Prune expired Trash entries and live shadow copies."""
        return purge_trash(self.context(), now)

    def maybe_purge_trash(self) -> int:
        """Prune at most hourly after a successful check."""
        return maybe_purge_trash(self.context())

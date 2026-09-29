"""Pure trash transitions over caller-supplied actors, time and pin records.

Refusals are returned values; accepted changes preserve field order and leave
input records untouched. Persistence and transaction ordering belong to callers.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from limn.pins.lifecycle import CLAIM_FIELDS, rev_after, signature
from limn.pins.model import Actor, Pin, TrashedPin, parse_pin


@dataclass(frozen=True)
class NotInTrash:
    """The Trash has no unexpired copy of this pin id."""

    pid: int


@dataclass(frozen=True)
class AlreadyLive:
    """A pin with this id is live again (restored before, or never deleted); restoring would duplicate it."""

    pid: int


def drop(pin: Pin, by: Actor, at: str) -> TrashedPin:
    """The Trash copy of a deleted pin: its record without the claim (never left behind), stamped with who and when."""
    record = {key: value for key, value in pin.record.items() if key not in CLAIM_FIELDS}
    record["dropped_at"] = at
    record["dropped_by"] = signature(by)
    return TrashedPin.from_record(record)


def find_trashed(trash: Sequence[TrashedPin], pid: int) -> TrashedPin | NotInTrash:
    """The newest copy of pin pid among the Trash entries given (the caller passes only unexpired ones)."""
    hits = [entry for entry in trash if entry.pin.core.id == pid]
    return hits[-1] if hits else NotInTrash(pid)


def restore(trashed: TrashedPin, live: bool, by: Actor, at: str) -> Pin | AlreadyLive:
    """Bring a Trash copy back as the pin it was: dropped_at/by removed, restored_at/by recorded, rev bumped.

    live says whether the id is already among the live pins; then nothing is restored.
    """
    if live:
        return AlreadyLive(trashed.pin.core.pid)  # the id find_trashed() matched
    record = {key: value for key, value in trashed.record.items() if key not in ("dropped_at", "dropped_by")}
    record["restored_at"] = at
    record["restored_by"] = signature(by)
    record["rev"] = rev_after(trashed.pin.core.rev)
    return parse_pin(record)

"""Pure Trash visibility and expiry rules shared by listing and Trash writes."""

from collections.abc import Sequence

from limn.pins.model import Pin, TrashedPin
from limn.pins.position import epoch as parse_epoch


def expires_ts(entry: TrashedPin, days: int) -> float | None:
    """Epoch seconds at which a Trash entry expires (dropped_at + days), or None if it has no readable dropped_at."""
    t = parse_epoch(entry.dropped.at if entry.dropped is not None else None)
    return None if t is None else t + days * 86400


def expired(entry: TrashedPin, days: int, now: float) -> bool:
    """Is Trash entry past its expiry at epoch now? An entry whose age cannot be read never expires."""
    t = expires_ts(entry, days)
    return t is not None and now > t


def unexpired(entries: Sequence[TrashedPin], days: int, now: float) -> list[TrashedPin]:
    """The Trash entries still restorable at epoch now, in their order."""
    return [entry for entry in entries if not expired(entry, days, now)]


def without_live_shadows(entries: Sequence[TrashedPin], pins: Sequence[Pin]) -> list[TrashedPin]:
    """Trash entries whose ids have no authoritative live pin, in their stored order."""
    live_ids = {pin.core.id for pin in pins}
    return [entry for entry in entries if entry.pin.core.id not in live_ids]

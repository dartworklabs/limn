"""Pure claims transitions over caller-supplied actors, time and pin records.

Refusals are returned values; accepted changes preserve field order and leave
input records untouched. Persistence and transaction ordering belong to callers.
"""

from dataclasses import dataclass
from typing import Any

from limn.pins.lifecycle import CLAIM_FIELDS, rev_after, signature
from limn.pins.model import Actor, Claim, DonePin, OpenPin, Pin, ReviewPin


@dataclass(frozen=True)
class ClaimRequest:
    """A claim command with positive minute values, even when created outside HTTP.

    The HTTP boundary clamps its separate ceiling; internal callers may use a longer positive lifetime.
    """

    ttl_min: int
    eta_min: int | None = None

    def __post_init__(self) -> None:
        """Reject durations that would make a new marker expired or have a non-integer minute count."""
        if type(self.ttl_min) is not int or self.ttl_min < 1:
            raise ValueError("ttl_min must be a positive integer")
        if self.eta_min is not None and (type(self.eta_min) is not int or self.eta_min < 1):
            raise ValueError("eta_min must be a positive integer")


@dataclass(frozen=True)
class ClaimClosedPin:
    """A closed pin cannot be claimed; the pin travels along for the 409 body."""

    pin: ReviewPin | DonePin


@dataclass(frozen=True)
class ClaimedByOther:
    """Someone else holds a live claim; the 409 body tells who, until when, and their estimate."""

    claimed_by: Any
    claim_until: Any
    eta_ts: Any


@dataclass(frozen=True)
class NotClaimed:
    """Unclaiming a pin that had no claim changes nothing; the pin is shown with any stray claim field cleared."""

    pin: Pin


def claim(
    pin: Pin, by: Actor, now: float, at: str, request: ClaimRequest, legacy_start: float | None
) -> OpenPin | ClaimClosedPin | ClaimedByOther:
    """Place or extend the in-progress marker on an open pin; a closed pin is refused.

    now is epoch seconds and at the same moment as the store's time string. legacy_start is the epoch of an old
    claim's claimed_at, used only to backfill claim_ts when extending a claim written before claim_ts existed.
    """
    match pin:
        case OpenPin():
            return claim_open(pin, by, now, at, request, legacy_start)
        case ReviewPin() | DonePin():
            return ClaimClosedPin(pin)


def claim_open(
    pin: OpenPin, by: Actor, now: float, at: str, request: ClaimRequest, legacy_start: float | None
) -> OpenPin | ClaimedByOther:
    """An open pin's claim rule: another identity's live claim refuses; the same identity extends; otherwise a new claim.

    An extension keeps the start (claimed_at/claim_ts) and re-measures claim_until from now; eta_ts is reset only when
    an estimate is given. A new claim drops every earlier claim field first - stray ones kept among the pin's fields
    too - so a stale estimate never survives.
    """
    held = pin.claim if pin.claim is not None and pin.claim.holds(now) else None
    if held is not None and held.by.get("login") != by.login:
        return ClaimedByOther(held.by, held.until, held.eta)
    record = dict(pin.record)
    if held is None:
        for key in CLAIM_FIELDS:
            record.pop(key, None)
        record["claimed_at"] = at
        record["claim_ts"] = now
    elif held.start is None:
        record["claim_ts"] = legacy_start or now
    record["claimed_by"] = signature(by)
    record["claim_until"] = now + request.ttl_min * 60
    if request.eta_min is not None:
        record["eta_ts"] = now + request.eta_min * 60
    record["rev"] = rev_after(pin.core.rev)
    return OpenPin.from_record(record)


def unclaim(pin: Pin) -> OpenPin | NotClaimed:
    """Clear the in-progress marker, whoever asks (the trust model restricts nothing here); rev goes up only if there was one.

    Only an open pin can hold a claim. Any other pin, or an open one without a claim, comes back as NotClaimed, shown
    with every stray claim field (one kept among its fields, not a claim) cleared; nothing is written for it.
    """
    cleared = {key: value for key, value in pin.record.items() if key not in CLAIM_FIELDS}
    match pin:
        case OpenPin(claim=Claim()):
            cleared["rev"] = rev_after(pin.core.rev)
            return OpenPin.from_record(cleared)
        case OpenPin() | ReviewPin() | DonePin():
            return NotClaimed(type(pin).from_record(cleared))

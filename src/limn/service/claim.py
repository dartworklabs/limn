"""The in-progress marker: claim and unclaim (docs/handbook/api.md §처리 중 표시).

A co-author and their agent can work on the same pin at the same time. A TTL'd optimistic marker reduces conflicts -
it's a signal, not a lock: nothing stops closing or force-claiming a pin another identity holds a valid claim on.
Neither shell sends a notice.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from limn.pins.lifecycle import ClaimClosedPin, ClaimedByOther, ClaimRequest, NotClaimed, claim, unclaim
from limn.pins.model import DonePin, OpenPin, PinNotFound, ReviewPin, parse_pin
from limn.pins.position import epoch
from limn.service.context import PinContext, Row, typed_actor
from limn.store import find_pin


def claim_pin(
    ctx: PinContext, pid: int, actor: Mapping[str, Any], ttl_min: int, eta_min: int | None = None
) -> OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound:
    """Place or extend the in-progress marker under the pin lock; written only when the claim is placed.

    The rule is limn.pins.lifecycle.claim(): a closed pin or another identity's live claim is refused (409 over HTTP),
    the same identity extends. The clock is read once here - epoch and store string of the same moment.
    """

    def fn(rows: list[Row]) -> tuple[OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound, bool]:
        """The transact() step: claim pin pid for actor; written only when the claim is placed."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        result = claim(
            parse_pin(r),
            typed_actor(actor),
            ctx.epoch(),
            ctx.now(),
            ClaimRequest(ttl_min, eta_min),
            epoch(r.get("claimed_at")),
        )
        if isinstance(result, OpenPin):
            r.clear()
            r.update(result.record)
            return result, True
        return result, False

    return ctx.store.transact(fn)[1]


def unclaim_pin(
    ctx: PinContext, pid: int, actor: Mapping[str, Any]
) -> OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound:
    """Clear the in-progress marker, whoever asks (actor is not checked); written only when there was a claim."""

    def fn(rows: list[Row]) -> tuple[OpenPin | NotClaimed | PinNotFound, bool]:
        """The transact() step: drop pin pid's claim fields, or NotClaimed with nothing written."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        result = unclaim(parse_pin(r))
        if isinstance(result, NotClaimed):
            return result, False
        r.clear()
        r.update(result.record)
        return result, True

    return ctx.store.transact(fn)[1]

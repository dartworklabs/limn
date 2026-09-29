"""HTTP input and answers for pin claim and unclaim."""

from collections.abc import Callable
from typing import Any, Protocol, TypeAlias

from limn.features.pins.claims import input as claim_input
from limn.features.pins.claims.rules import ClaimClosedPin, ClaimedByOther, NotClaimed
from limn.features.pins.claims.service import PinClaims
from limn.pins.model import DonePin, OpenPin, PinNotFound, Record, ReviewPin
from limn.web.answers import accepted
from limn.web.errors import HTTPError

Body: TypeAlias = dict[str, object]
Show: TypeAlias = Callable[[Record], object]


class ClaimsApp(Protocol):
    """Run-specific collaborators used by claim and unclaim."""

    pin_claims: PinClaims

    def public(self, record: Record) -> dict[str, Any]:
        """Render one pin record for the API."""
        ...


def claim(app: ClaimsApp, pid: int, actor: dict[str, Any], body: dict[str, Any]) -> Body:
    """Parse, decide, and answer POST /api/pins/{id}/claim after shared guards."""
    ttl, eta = accepted(claim_input.parse_claim_body(body))
    return claim_answer(app.pin_claims.claim_pin(pid, actor, ttl, eta), ttl, eta, app.public)


def unclaim(app: ClaimsApp, pid: int, actor: dict[str, Any]) -> Body:
    """Decide and answer POST /api/pins/{id}/unclaim after shared guards."""
    return unclaim_answer(app.pin_claims.unclaim_pin(pid, actor), app.public)


def claim_answer(
    result: OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound, ttl: int, eta: int | None, show: Show
) -> Body:
    """POST /api/pins/{id}/claim: the pin and the ttl/eta actually applied (clamped values), or a 409."""
    match result:
        case OpenPin(record=record):
            out: Body = {"ok": True, "pin": show(record), "ttl_min_applied": ttl}
        case PinNotFound():
            out = {"ok": False, "pin": None, "ttl_min_applied": ttl}
        case ClaimClosedPin(pin=ReviewPin(record=record) | DonePin(record=record)):
            raise HTTPError(409, "done", pin=show(record), reason="done")
        case ClaimedByOther(claimed_by=holder, claim_until=until, eta_ts=eta_ts):
            raise HTTPError(409, "claimed", claimed_by=holder, claim_until=until, eta_ts=eta_ts, reason="claimed")
    if eta is not None:
        out["eta_min_applied"] = eta  # the clamped value, if sent above the ceiling (240)
    return out


def unclaim_answer(result: OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound, show: Show) -> Body:
    """POST /api/pins/{id}/unclaim: the pin as it stands (no claim), or ok:false for an unknown id."""
    match result:
        case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
            return {"ok": True, "pin": show(record)}
        case NotClaimed(pin=OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record)):
            return {"ok": True, "pin": show(record)}
        case PinNotFound():
            return {"ok": False, "pin": None}

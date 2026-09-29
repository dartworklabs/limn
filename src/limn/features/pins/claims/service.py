"""Claim and unclaim transactions for the in-progress marker."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from limn.features.pins.claims.rules import ClaimClosedPin, ClaimedByOther, ClaimRequest, NotClaimed, claim, unclaim
from limn.pins.model import DonePin, OpenPin, Pin, PinNotFound, ReviewPin
from limn.pins.position import epoch
from limn.service.context import PinContext, load_pin, typed_actor


@dataclass(frozen=True)
class PinClaims:
    """The claim routes bound to one application's pin context factory."""

    context: Callable[[], PinContext]

    def claim_pin(
        self, pid: int, actor: Mapping[str, Any], ttl_min: int, eta_min: int | None = None
    ) -> OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound:
        """Place or extend the in-progress marker under the pin lock; written only when the claim is placed.

        The rule is limn.features.pins.claims.rules.claim(): a closed pin or another identity's live claim is refused (409 over HTTP),
        the same identity extends. The context supplies epoch time for expiry and a separate display timestamp
        for the stored claim; each is read once when evaluating the request.
        """

        ctx = self.context()

        def fn(pins: list[Pin]) -> tuple[OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound, bool]:
            """The transact() step: claim pin pid for actor; written only when the claim is placed."""
            found = load_pin(pins, pid)
            if isinstance(found, PinNotFound):
                return found, False
            i, pin = found
            held = pin.claim if isinstance(pin, OpenPin) else None
            result = claim(
                pin,
                typed_actor(actor),
                ctx.epoch(),
                ctx.now(),
                ClaimRequest(ttl_min, eta_min),
                epoch(held.at) if held is not None else None,
            )
            if isinstance(result, OpenPin):
                pins[i] = result
                return result, True
            return result, False

        return ctx.store.transact(fn)[1]

    def unclaim_pin(
        self, pid: int, actor: Mapping[str, Any]
    ) -> OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound:
        """Clear the in-progress marker, whoever asks (actor is not checked); written only when there was a claim."""

        ctx = self.context()

        def fn(pins: list[Pin]) -> tuple[OpenPin | NotClaimed | PinNotFound, bool]:
            """The transact() step: drop pin pid's claim fields, or NotClaimed with nothing written."""
            found = load_pin(pins, pid)
            if isinstance(found, PinNotFound):
                return found, False
            i, pin = found
            result = unclaim(pin)
            if isinstance(result, NotClaimed):
                return result, False
            pins[i] = result
            return result, True

        return ctx.store.transact(fn)[1]

"""HTTP input for claiming and unclaiming a pin."""

from collections.abc import Mapping
from typing import Any, NamedTuple

from limn.pins.shapes import is_finite_num
from limn.web.errors import InputRejected

Json = Mapping[str, Any]

CLAIM_TTL_DEFAULT = 120  # minutes - lock duration used when neither ttl_min nor eta_min is given for a claim (docs/handbook/api.md §처리 중 표시 (claim))
CLAIM_TTL_MIN = 1
# the lock auto-expiring is a safety net - at 480 a stuck agent held a pin for half a day (observed 23 times)
CLAIM_TTL_MAX = 120
CLAIM_ETA_MIN = 1  # minutes - estimated time to handle (eta_min). Shown in the UI rounded up to 5-minute steps
CLAIM_ETA_MAX = 240
CLAIM_TTL_FLOOR = 30  # if only eta_min is given, the lock is min(ceiling, max(this floor, eta x 2)) - even a short estimate holds for 30 min


class ClaimBody(NamedTuple):
    """A claim's minutes until the marker lapses (clamped) and its optional estimate (clamped)."""

    ttl: int
    eta: int | None


def _claim_int(d: Json, key: str, lo: int, hi: int) -> int | None | InputRejected:
    """One optional integer from the body. None if absent. Refused if not an integer or below lo; clamped to hi if it
    exceeds the ceiling.

    Clamping is for backward compatibility - so an agent that still sends the old ttl_min=480 doesn't break
    when trying to extend with the same value after the ceiling was lowered to 120, instead of getting a 400.
    The value actually applied is returned as *_applied in the response."""
    if key not in d:
        return None
    v = d[key]
    if not is_finite_num(v) or int(v) != v:
        return InputRejected("%s 은 정수여야 합니다." % key, "not_integer")
    n = int(v)
    if n < lo:
        return InputRejected(
            "%s 은 %d 이상이어야 합니다(상한 %d 를 넘으면 %d 로 깎아 받습니다)." % (key, lo, hi, hi), "too_small"
        )
    return min(n, hi)


def parse_claim_body(d: Json) -> ClaimBody | InputRejected:
    """The claim body -> (ttl_min, eta_min or None). Both are optional; eta_min is checked first.

    eta_min (1..240) is the estimated time to handle - shown in the viewer as "in progress - about 15 min -
    around 20:40". ttl_min (1..120) is the time until the lock auto-expires (a safety net). Values past the
    ceiling are clamped to it (compatible with the legacy ttl_min 480). If ttl_min is omitted, it's
    min(120, max(30, eta x 2)) when eta_min is given, otherwise 120."""
    eta = _claim_int(d, "eta_min", CLAIM_ETA_MIN, CLAIM_ETA_MAX)
    if isinstance(eta, InputRejected):
        return eta
    ttl = _claim_int(d, "ttl_min", CLAIM_TTL_MIN, CLAIM_TTL_MAX)
    if isinstance(ttl, InputRejected):
        return ttl
    if ttl is None:
        ttl = min(CLAIM_TTL_MAX, max(CLAIM_TTL_FLOOR, eta * 2)) if eta is not None else CLAIM_TTL_DEFAULT
    return ClaimBody(ttl, eta)

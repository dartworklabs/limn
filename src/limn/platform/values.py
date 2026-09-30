"""The shape of a JSON value as json.loads gives it: integer, number, and finite number rules.

JSON has no separate boolean-free integer type in Python: json.loads turns `true` into True, and bool is a subclass of
int, so `isinstance(v, int)` alone would let `true` pass as a line number, a pin id or an epoch time. Every reader of
a stored record, a request body, events.jsonl or builds.json asks these predicates instead.

Pure and standard-library only, so any module - domain, store or edge - may use it.
"""

from math import isfinite
from typing import TypeGuard


def is_int(v: object) -> TypeGuard[int]:
    """A JSON integer: an int that is not a bool."""
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v: object) -> TypeGuard[int | float]:
    """A JSON number: an int or float that is not a bool (epoch seconds, frac coordinates, scores)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_finite_num(v: object) -> TypeGuard[int | float]:
    """A JSON number representable as a finite float; oversized JSON integers are refused instead of raising."""
    if not is_num(v):
        return False
    try:
        return isfinite(v)
    except OverflowError:
        return False


def wire_value(v: object) -> object:
    """v as a JSON response can carry it: a number that is not finite (NaN, an Infinity, an integer no float holds)
    becomes None - at any depth of a list or an object - and everything else is kept. Lists and objects come back as
    copies, so the stored value a reader passed in is never changed."""
    if is_num(v):
        return v if is_finite_num(v) else None
    if isinstance(v, list):
        return [wire_value(x) for x in v]
    if isinstance(v, dict):
        return {k: wire_value(x) for k, x in v.items()}
    return v

"""wire_value: a stored JSON value as a response can carry it (limn.platform.values)."""

import math

from limn.platform.values import wire_value

HUGE = 10**400  # a JSON integer no float can hold


def test_a_non_finite_number_becomes_none_at_any_depth() -> None:
    """NaN, both infinities and an integer no float holds are None in a scalar, a list and an object, nested."""
    for bad in (float("nan"), float("inf"), -float("inf"), HUGE):
        assert wire_value(bad) is None
        assert wire_value([1, bad, {"k": [bad, 2]}]) == [1, None, {"k": [None, 2]}]


def test_finite_numbers_booleans_strings_and_none_are_kept() -> None:
    """0, 0.0, 1.0, a negative number, a boolean, a string and None pass exactly - a boolean is not a number here."""
    for kept in (0, 0.0, 1.0, -2.5, True, False, "NaN", None):
        assert wire_value(kept) == kept
        assert type(wire_value(kept)) is type(kept)


def test_the_input_is_never_changed_and_containers_are_copies() -> None:
    """A list or an object holding a NaN comes back as a new container; the original keeps its NaN."""
    stored = {"a": [float("nan")]}
    out = wire_value(stored)
    assert out == {"a": [None]}
    assert out is not stored and isinstance(out, dict) and out["a"] is not stored["a"]
    assert math.isnan(stored["a"][0])

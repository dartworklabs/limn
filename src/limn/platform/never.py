"""The last arm of a `match` over a closed type, on every supported Python (typing.assert_never needs 3.11)."""

from typing import NoReturn


def assert_never(value: NoReturn) -> NoReturn:
    """Mark a match arm the type checker proves unreachable: called with anything but an exhausted subject, the
    call is a type error (the checker names the cases left). Raises AssertionError if it ever runs, which is a defect:
    a value outside the closed type reached the match."""
    raise AssertionError(f"a value outside its closed type reached a match: {value!r}")

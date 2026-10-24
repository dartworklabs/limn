"""The `suggest` field of a LaTeX line pin: the exact text that replaces the pin's lines.

The contract is docs/handbook/api.md §핀 레코드 스키마 and the decision docs/adr/0020-suggested-edit-pins.md. A pin
records a suggestion as {"base": ..., "text": ...}. base is the source lines lo..hi the author saw, joined with "\\n"
and without a trailing newline; text replaces exactly those lines, in the same form, and "" deletes them. Neither holds
a carriage return: line terminators are compared without it. The record check (limn.pins.record) accepts a stored
value by its shape alone (is_suggest_record); readers lift it with suggestion_of; the request parser builds a
Suggestion and the editing rules store Suggestion.to_record(). Whether the source still reads as base is computed on
every read (suggest_state) and never stored. Pure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypeGuard

# What a stored suggestion's lines say now (GET /api/pins `suggest_state`): replace them (ready), leave them because
# they no longer read as the base (changed), or leave them because they cannot be compared (unknown).
SuggestState: TypeAlias = Literal["ready", "changed", "unknown"]


@dataclass(frozen=True)
class Suggestion:
    """A suggested edit: base, the lines the author saw, and text, what replaces them - each joined with "\\n", with
    no trailing newline and no carriage return."""

    base: str
    text: str

    def __post_init__(self) -> None:
        """Reject a value the stored form cannot mean: a base or text that is not a string, or that still holds a
        carriage return (the parsers remove every one)."""
        if not (isinstance(self.base, str) and isinstance(self.text, str)):
            raise ValueError("a suggestion's base and text are strings")
        if "\r" in self.base or "\r" in self.text:
            raise ValueError("a suggestion's base and text hold no carriage return")

    def to_record(self) -> dict[str, str]:
        """The shape a record stores and the API answers: {"base", "text"}, in that order."""
        return {"base": self.base, "text": self.text}


def without_cr(text: str) -> str:
    """text with every carriage return removed: how a suggestion's base and text, and the lines they are compared
    with, are read."""
    return text.replace("\r", "")


def lines_text(lines: Sequence[str], lo: int, hi: int) -> str | None:
    """Lines lo..hi (1-based, inclusive) of lines as a suggestion's base reads them: joined with "\\n", no trailing
    newline, every carriage return removed. None when the range does not lie within lines - an empty file, or one the
    checked read could not open (limn.platform.files.tex_lines gives [] then), included."""
    if not 1 <= lo <= hi <= len(lines):
        return None
    return without_cr("\n".join(lines[lo - 1 : hi]))


def is_suggest_record(v: object) -> TypeGuard[dict[str, Any]]:
    """Is v a stored `suggest` the store may trust? An object whose base and text are strings. Keys it does not know
    pass, as an el's do, so a later version may add one without an older one breaking the line."""
    return isinstance(v, dict) and isinstance(v.get("base"), str) and isinstance(v.get("text"), str)


def suggestion_of(v: object) -> Suggestion | None:
    """The suggestion a stored `suggest` holds, with any carriage return removed (only a hand-edited line can carry
    one), or None when v is missing, null or not a shape is_suggest_record accepts. Total: never raises."""
    if not is_suggest_record(v):
        return None
    return Suggestion(without_cr(v["base"]), without_cr(v["text"]))


def suggest_state(suggestion: Suggestion, current: str | None, stale: bool) -> SuggestState:
    """Whether a suggestion still fits its pin's lines. "unknown" when the pin lost its place (stale) or its lines
    could not be read - current None: the file is outside the manuscript tree, unreadable, or shorter than the range;
    otherwise "ready" when current (the lines lo..hi now, as lines_text reads them) is the base, else "changed"."""
    if stale or current is None:
        return "unknown"
    return "ready" if without_cr(current) == suggestion.base else "changed"

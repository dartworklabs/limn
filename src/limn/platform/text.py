"""Whitespace normalization and bounded text, independent of any capability."""

from typing import TypeAlias

# Text a person writes and no code reads for meaning: a note, a reply, a close reason. Decision, model and protocol
# modules name such a value FreeText instead of str; it is the reviewed exception of the primitive-type rule
# (tools/check_fitness.py PRIMITIVE_ALIASES), so a str there otherwise means a domain value still to be typed.
FreeText: TypeAlias = str


def truncate_quote(s: object, n: int = 60) -> str:
    """Truncates a quote to at most n characters (ellipsis included, matching the «...» convention).

    If a truncated quote looked like a complete sentence, it would be confusing when trying to relocate the
    source - the truncation mark is what tells the user/agent to read this as a "search hint", not the
    "whole thing". When truncating, the ellipsis is appended after n-1 characters of body text, so the
    result is always n characters or fewer (never n+1 from n characters plus the ellipsis)."""
    text = str(s)
    return text[: n - 1] + "…" if len(text) > n else text


def flat(s: object, n: int) -> str:
    """Collapses whitespace/newlines to a single space and truncates at n characters (with an ellipsis if cut).
    None and "" both give "". The one rule for a text shown on one line: pins.md's thread posts and close replies
    (limn.pins.listing.render), and the excerpt of an events.jsonl notice (limn.collaboration.events.make_event)."""
    return truncate_quote(" ".join(str(s or "").split()), n)

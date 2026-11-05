"""Narrow pin query bindings for document polling and revision attribution."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from limn.pins.revision import RevisionPin

# One pin of one document (id, document key) for the changes view, its stored paths placed in the run's registered
# coordinates and named by the revision owner's callable (limn.pins.application.PinReadView.revision_pin).
RevisionPinQuery: TypeAlias = Callable[[int, str, Callable[[Path], str | None]], RevisionPin | None]


@dataclass(frozen=True)
class PinCountQueries:
    """Counts and a change token; normal reads and anchor-refreshing reads remain distinct."""

    counts_by_document: Callable[[set[str]], tuple[dict[str, int], int]]
    state_counts: Callable[[], dict[str, int]]
    change_token: Callable[[], str]

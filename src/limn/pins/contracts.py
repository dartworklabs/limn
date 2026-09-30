"""Narrow pin query bindings for document polling and revision attribution."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeAlias

from limn.pins.revision import RevisionPin


class PinDocument(Protocol):
    """Only the document folder required to locate a moved pin or changed range."""

    @property
    def src(self) -> Path:
        """The folder limiting historical path-tail matching."""
        ...


RevisionPinQuery: TypeAlias = Callable[[int, str, PinDocument, Callable[[Path], str | None]], RevisionPin | None]


@dataclass(frozen=True)
class PinCountQueries:
    """Counts and a change token; normal reads and anchor-refreshing reads remain distinct."""

    counts_by_document: Callable[[set[str]], tuple[dict[str, int], int]]
    state_counts: Callable[[], dict[str, int]]
    change_token: Callable[[], str]

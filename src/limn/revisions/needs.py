"""What revision attribution needs from the owner of pins, declared by this slice.

No module of limn.revisions imports another feature. The composition root passes the pin owner's query to
assemble_revisions(), and the type checker proves there that the supplied values have the members named here. Every
member is read-only: revisions reads these facts and never rebuilds or stores the supplier's value.
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol


class PinAnchor(Protocol):
    """The text a pin's range was anchored to when stored, whitespace-collapsed as revisions.scope compares lines."""

    @property
    def head(self) -> str:
        """The first anchored line of the range; never empty."""
        ...

    @property
    def tail(self) -> str:
        """The last anchored line of the range, or "" when none was stored."""
        ...

    @property
    def head_off(self) -> int:
        """How many lines below the range's first line (lo) the head line sits."""
        ...

    @property
    def tail_off(self) -> int:
        """How many lines above the range's last line (hi) the tail line sits."""
        ...


class PinChange(Protocol):
    """One range the closer recorded as changed, on the new side of the commit that closed the pin."""

    @property
    def file(self) -> str:
        """The changed file as the query's path rule answered it (repository-relative, POSIX)."""
        ...

    @property
    def lo(self) -> int:
        """The first changed line, 1-based."""
        ...

    @property
    def hi(self) -> int:
        """The last changed line, 1-based and inclusive."""
        ...


class LocatedPin(Protocol):
    """A pin and where it sits now - all that the pure attribution in revisions.scope reads."""

    @property
    def id(self) -> int:
        """The pin's number."""
        ...

    @property
    def relative_path(self) -> str | None:
        """The pin's file as the query's path rule answered it, or None when the rule could not place it."""
        ...

    @property
    def lo(self) -> int | None:
        """The first line of the pin's range as last synced, 1-based; None for a pin without a line range."""
        ...

    @property
    def hi(self) -> int | None:
        """The last line of the pin's range as last synced, inclusive; None for a pin without a line range."""
        ...

    @property
    def stale(self) -> bool:
        """Whether sync lost the pin's anchor, so its lines are those of the text before the edit."""
        ...

    @property
    def anchor(self) -> PinAnchor | None:
        """The anchored text, or None for a pin stored without a usable anchor."""
        ...


class PinProjection(LocatedPin, Protocol):
    """What the pin query answers: the located pin plus its close record, still unmatched to any commit."""

    @property
    def changes(self) -> Sequence[PinChange]:
        """The ranges recorded at the pin's current close; they count only on the commit close_ref names
        (revisions.core.matching_pin_changes)."""
        ...

    @property
    def close_ref(self) -> str | None:
        """The closer's free-text reference to a commit or pull request, or None when none was given."""
        ...


class PinQueryDocument(Protocol):
    """The part of the compared document the pin query may read."""

    @property
    def src(self) -> Path:
        """The document's build root, which bounds where a stored path may be found again."""
        ...


class PinQuery(Protocol):
    """The pin owner's read for one pin of one document."""

    def __call__(
        self,
        pin_id: int,
        document_key: str,
        document: PinQueryDocument,
        relative: Callable[[Path], str | None],
        /,
    ) -> PinProjection | None:
        """Project pin pin_id of the document with key document_key, or None when no such pin belongs to it.

        The supplier locates every stored path as the checkout has it now and asks `relative` for the form revisions
        compares with git paths; a recorded change whose path cannot be located or placed that way is left out.
        """
        ...

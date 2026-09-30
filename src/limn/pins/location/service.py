"""Run-bound PDF selection and source-range reads."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from limn.pins.location import range as source_range
from limn.pins.location.range import SourceRange
from limn.pins.location.resolve import PickContext, Picked, PickedRegion, PickRefusal, Selection, pick
from limn.runtime.documents import Doc


@dataclass(frozen=True)
class PinLocationService:
    """Resolve PDF selections and source ranges against one server run."""

    context: Callable[[], PickContext]

    def resolve(self, doc: Doc, request: Selection) -> Picked | PickedRegion | PickRefusal:
        """Return source lines, a view-only region or a named refusal."""
        return pick(doc, request, self.context())

    def snippet(self, rng: SourceRange, levels: bool) -> dict[str, Any]:
        """Render a source range and optionally its range ladder."""
        return source_range.snippet_api(rng, levels, self.context().envs)

    def overlaps(self, rng: SourceRange) -> dict[str, Any]:
        """Find open pins that intersect a validated source range."""
        return source_range.overlaps_api(rng, self.context().overlaps)

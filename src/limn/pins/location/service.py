"""Run-bound PDF selection and source-range reads."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from limn.pins.location import range as source_range
from limn.pins.location.figure import PickedElement
from limn.pins.location.range import SourceRange, no_boxes
from limn.pins.location.resolve import (
    PageOnScreen,
    PickContext,
    Picked,
    PickedRegion,
    PickRefusal,
    Selection,
    pick,
    range_boxes,
)
from limn.runtime.documents import Doc


@dataclass(frozen=True)
class PinLocationService:
    """Resolve PDF selections and source ranges against one server run."""

    context: Callable[[], PickContext]

    def resolve(self, doc: Doc, request: Selection) -> Picked | PickedElement | PickedRegion | PickRefusal:
        """Return source lines, a figure element's lines, a region or a named refusal."""
        return pick(doc, request, self.context())

    def snippet(
        self,
        doc: Doc,
        rng: SourceRange,
        levels: bool,
        source_ladder: bool = True,
        text: bool = False,
        on_screen: PageOnScreen | None = None,
    ) -> dict[str, object]:
        """Render a source range and optionally its range ladder: the source ladder, or the raw rung alone when the
        document's ladder comes from an element map - and, with text, its exact lines (range.snippet_api).

        With a page to measure against (on_screen - the caller decides whether this answer's rungs may carry marks,
        limn.pins.location.http.snippet), every rung also carries where its lines print on that build's PDF. The
        build's facts are read once here and bound for the whole answer, not per rung; without a page the ladder is
        the one this route has always answered."""
        ctx = self.context()
        boxes = no_boxes
        if on_screen is not None:
            publication = ctx.builds.publication(doc, on_screen.build, ctx.state)
            built = publication.built_lines(rng.file)
            boxes = range_boxes(doc, rng.file, built, rng.lines, publication.pdf, on_screen.pages)
        return source_range.snippet_api(rng, levels, ctx.envs, source_ladder, text, boxes)

    def overlaps(self, rng: SourceRange) -> dict[str, Any]:
        """Find open pins that intersect a validated source range."""
        return source_range.overlaps_api(rng, self.context().overlaps)

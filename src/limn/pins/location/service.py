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
        limn.pins.location.http.snippet), every rung also carries where its lines print on that build's PDF, and the
        answer names that build (`boxes_build`, docs/handbook/api.md §줄 핀의 상자 (`boxes`)). The build's facts are
        read once here and bound for the whole answer, not per rung; without a page the ladder is the one this route
        has always answered.

        The name travels because a client cannot work it out: the pieces are places on the pages of the build this
        run has when it answers, and a build that finishes inside the round trip is measured against while the client
        is still showing the one before it. Labelled with what the client believed when it asked, those pieces would
        be drawn over pages they are not on. The name comes with an answer that could measure nothing against that
        build too - no record of its lines, no mark over the line cap - because "no mark" is an answer about that
        build and no other; it comes at all only when a build with pages was there to measure against.

        A build that kept no record of the lines it read (one made by an older Limn) answers no marks at all, as the
        pin listing does for such a build (limn.builds.queries.BuildQueries.boxes,
        docs/adr/0049-pin-marks-follow-the-range.md D7). A request here
        carries only a file and a line range of the file as it is today, and with no record nothing says those
        numbers name the same lines in the build that drew the page on screen - measuring today's numbers against an
        old layout is the one failure that rule exists to prevent. A pick does not fall here: it holds SyncTeX's own
        answer for that build and that drag, so the build's numbers are known even without a record."""
        ctx = self.context()
        boxes = no_boxes
        if on_screen is not None:
            publication = ctx.builds.publication(doc, on_screen.build, ctx.state)
            built = publication.built_lines(rng.file)
            if built is not None:
                boxes = range_boxes(doc, rng.file, built, rng.lines, publication.pdf, on_screen.pages).pieces
        return source_range.snippet_api(
            rng,
            levels,
            ctx.envs,
            source_ladder,
            text,
            boxes,
            boxes_build=None if on_screen is None else on_screen.build,
        )

    def overlaps(self, rng: SourceRange) -> dict[str, Any]:
        """Find open pins that intersect a validated source range."""
        return source_range.overlaps_api(rng, self.context().overlaps)

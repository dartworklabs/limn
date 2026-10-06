"""What pin placement and pin views need from the owner of builds, declared by this slice.

No module of limn.pins imports another feature. The composition root (server.py) passes the build owner's query
bundle to assemble_pins(), and the type checker proves there that the bundle and every value it answers have the
members named here. Only the members pins reads are declared, and every one is read-only: pins consumes these facts
and never rebuilds, stores or writes back the supplier's value. No element map, build history or marker file crosses.
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, TypeAlias, runtime_checkable

from limn.pins.element import ElementFrac
from limn.runtime.documents import Doc
from limn.web.parse import DocumentFacts

# Lines lo..hi (1-based, inclusive) of a file named relative to the figure document's folder: (file, lo, hi).
SourceSpan: TypeAlias = tuple[str, int, int]


class BuildOnScreen(Protocol):
    """The build a drag was made on - the one named in the request, not whichever is current now: the PDFs a pick
    reads and names, and what a pick reports about that build's freshness."""

    @property
    def pdf(self) -> Path:
        """The PDF of that build; the input of SyncTeX and of the region's text extraction."""
        ...

    @property
    def region_pdf(self) -> Path:
        """The PDF a region answer names: for a figure document the one that build's map names, else the document's
        main file."""
        ...

    @property
    def stale(self) -> bool:
        """Whether the manuscript is newer than that build by more than two seconds."""
        ...

    @property
    def running(self) -> bool:
        """Whether a build of the document is running now, so its pages are being redrawn."""
        ...

    @property
    def latex_running(self) -> bool:
        """Whether that running build is in its LaTeX phase."""
        ...


class EstimationFacts(Protocol):
    """What deciding `est` reads of one document's builds (limn.pins.location.position.EstContext), with source
    equivalence already decided by the supplier."""

    @property
    def cur(self) -> str:
        """The name of the build on screen."""
        ...

    @property
    def exact_builds(self) -> frozenset[str]:
        """The names of the builds made from the same source as cur, cur included."""
        ...

    @property
    def built_at(self) -> float | None:
        """When the build on screen finished, in epoch seconds; None when unknown."""
        ...

    @property
    def built_src_mtime(self) -> float | None:
        """The manuscript's mtime when that build started, in epoch seconds; None when unknown."""
        ...


class HeadingStamps(Protocol):
    """The stamps of the build a document has on screen, as pins.md's document heading and a new region pin record
    them."""

    @property
    def head(self) -> str | None:
        """The short git hash that build's page images came from ("-" outside git); None when never built."""
        ...

    @property
    def built_at(self) -> str | None:
        """When that build finished, as the text the heading prints; None when unknown."""
        ...

    @property
    def build(self) -> str:
        """The name of that build - what a region pin stores as pdf_build."""
        ...


class FigureElement(Protocol):
    """One element of a figure's map, detached from the map: what a pin records of it and where its code is."""

    @property
    def id(self) -> str:
        """The element's map id."""
        ...

    @property
    def path(self) -> tuple[str, ...]:
        """The ids from the page root down to this element, root first."""
        ...

    @property
    def label(self) -> str | None:
        """The element's label; None when the map gives none (never "")."""
        ...

    @property
    def part(self) -> str | None:
        """The element's part name; None when the map gives none (never "")."""
        ...

    @property
    def impl(self) -> SourceSpan | None:
        """The lines of the element's shared implementation, or None. Shown only; never read through this value."""
        ...

    @property
    def frac(self) -> ElementFrac:
        """The element's box on its page in that build."""
        ...

    @property
    def source(self) -> SourceSpan | None:
        """The lines that drew the element, or None for an element drawn without code. The path is as the map gives
        it: pins checks where it leads before reading it (limn.pins.location.figure.read_source)."""
        ...

    @property
    def names(self) -> tuple[str, ...]:
        """For each id of path, in the same order, the name the map gives that element - its label, else its part,
        else ""."""
        ...


class ElementChoice(Protocol):
    """A drag on a figure page interpreted by the supplier: the element it chose and the ladder around it."""

    @property
    def chosen(self) -> FigureElement:
        """The element the drag chose."""
        ...

    @property
    def kind(self) -> str:
        """The pin kind of the choice, answered as the pick's `kind`."""
        ...

    @property
    def score(self) -> float:
        """How much of the drag the chosen element covers, 0..1."""
        ...

    @property
    def ladder(self) -> Sequence[tuple[str, FigureElement]]:
        """The rungs as (level name, element), nearest first: the chosen element, its ancestors, the whole figure."""
        ...


@runtime_checkable
class FigureMapUnavailable(Protocol):
    """The other answer to a drag on a figure page: that build has no usable map, or its map lacks the page.

    limn.pins.location.figure.pick_figure tells this answer from an ElementChoice at run time by isinstance, which
    for a Protocol asks only whether the value has a member named `reason`. An ElementChoice therefore must never
    have one; the location tests pass the supplier's two real values through pick_figure to hold that.
    """

    @property
    def reason(self) -> str:
        """The supplier's word for why there is no choice. Pins reads only its presence."""
        ...


class FollowedElement(Protocol):
    """Where a pinned element is on the map of the build on screen."""

    @property
    def page(self) -> int | None:
        """The page it is on now, 1-based; None when the map no longer has the element."""
        ...

    @property
    def frac(self) -> ElementFrac | None:
        """Its box on that page; None when the map no longer has the element."""
        ...

    @property
    def sync(self) -> str:
        """`ok` (same page and box as when pinned), `moved` or `lost` - answered as el_sync."""
        ...


# Follows one pinned element on one build's map, bound by the supplier: (element id, the page it was pinned on, its
# box then) -> where it is now. The caller never sees the map.
FollowElement: TypeAlias = Callable[[str, int, ElementFrac], FollowedElement]


class BuildAnswers(Protocol):
    """The six questions pins asks the owner of builds. Each answers a completed fact; none hands out a map, a
    history entry or a marker path, and none writes."""

    @property
    def publication(self) -> Callable[[Doc, str, Path], BuildOnScreen]:
        """The build a drag was made on, given the document, that build's name and the state folder."""
        ...

    @property
    def position(self) -> Callable[[Doc], EstimationFacts]:
        """The estimation facts of a document's builds."""
        ...

    @property
    def heading(self) -> Callable[[Doc], HeadingStamps]:
        """The stamps of the build a document has on screen."""
        ...

    @property
    def selection(self) -> Callable[[Doc, str, int, ElementFrac], ElementChoice | FigureMapUnavailable]:
        """The element a drag chose, given the figure document, the name of the build dragged on, the page (1-based)
        and the drag box as page fractions - or that this build's map cannot answer."""
        ...

    @property
    def elements(self) -> Callable[[Doc], FollowElement | None]:
        """The follower bound to the map of the build a document has on screen; None for a document without an
        element map or a build without a loadable one."""
        ...

    @property
    def document_facts(self) -> Callable[[Doc, Path, Path, int], DocumentFacts]:
        """The request-parsing facts of a document, given the manuscript root, the state folder and the dpi."""
        ...

"""Purpose-specific build answers; no artifact layout or parsed map crosses this surface."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

from limn.builds.values import Json
from limn.runtime.documents import Doc

if TYPE_CHECKING:
    from limn.web.parse import DocumentFacts

Frac: TypeAlias = tuple[float, float, float, float]
SourceLines: TypeAlias = tuple[str, int, int]


@dataclass(frozen=True)
class BuildHeading:
    """Optional stamps for a document heading, including an intentionally empty stamp."""

    head: str | None
    built_at: str | None
    build: str


@dataclass(frozen=True)
class DocumentBuild:
    """Detached build-owned fields of the brief and meta HTTP contracts, from one read of a document's build.

    brief is complete when the value is made. meta is read the first time it is asked for - the page sizes and the
    build stamps of the build the brief names - and is the same dict at every later access, so a caller that
    reports only the brief (GET /api/docs, the other documents of GET /api/meta) pays for nothing else."""

    brief: dict[str, Any]
    _read: Callable[[], Json] = field(repr=False, compare=False)
    _kept: list[Json] = field(default_factory=list, init=False, repr=False, compare=False)

    @property
    def meta(self) -> Json:
        """The build facts of GET /api/meta for the build `brief` names, read at the first access and kept."""
        if not self._kept:
            self._kept.append(self._read())
        return self._kept[0]


@dataclass(frozen=True)
class Publication:
    """Assets and pick status of the selected build, never the mutable current pointer. built_lines answers the lines
    of a manuscript file (a checkout path) as that build read them - a LaTeX build's inputs, a figure import's
    scripts - from the build's source record, or None when the build kept none for it; the record is read when asked,
    not when the publication is bound."""

    build: str
    pages: Path
    pdf: Path
    region_pdf: Path
    stale: bool
    running: bool
    latex_running: bool
    built_lines: Callable[[Path], Sequence[str] | None]


@dataclass(frozen=True)
class PositionHistory:
    """Builds sharing the current source and times needed for legacy pin estimation."""

    cur: str
    exact_builds: frozenset[str]
    built_at: float | None
    built_src_mtime: float | None


@dataclass(frozen=True)
class OutlineInput:
    """Bounded text published with one build; absent or unsafe text is empty."""

    build: str
    text: str


@dataclass(frozen=True)
class ElementFact:
    """One selected element's pin identity and source span, not a traversable map node. names holds, for each id of
    path (root first), the name the map gives that element - its label, else its part - or "" where it gives none."""

    id: str
    path: tuple[str, ...]
    label: str | None
    part: str | None
    impl: SourceLines | None
    frac: Frac
    source: SourceLines | None
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ElementSelection:
    """Completed drag interpretation and nearest-first ladder in its chosen source file."""

    chosen: ElementFact
    kind: str
    score: float
    ladder: tuple[tuple[str, ElementFact], ...]
    fill: float = 0.0
    rival: bool = False


@dataclass(frozen=True)
class SelectionUnavailable:
    """The selected figure build has no usable map or requested page."""

    reason: str = "figure_map_unavailable"


@dataclass(frozen=True)
class ElementPosition:
    """Completed follow result: synchronization and, when present, current page and box."""

    page: int | None
    frac: Frac | None
    sync: str


ElementFollower: TypeAlias = Callable[[str, int, Frac], ElementPosition]

# A pin's mark: the pieces one line range draws, each the page (1-based) and that piece's box as fractions of that
# page. The pin consumer declares the same shape (limn.pins.needs.MarkPieces); nothing of either side's crosses.
MarkPieces: TypeAlias = tuple[tuple[int, Frac], ...]
# Where one range of one already-chosen file prints: (lo, hi) -> that range's pieces.
MarkRange: TypeAlias = Callable[[int, int], MarkPieces]
# Which lines of the build one range of that file is: (lo, hi) -> the build's line range, or None when nothing can be
# measured for it because the range no longer stands whole in the lines that build read
# (limn.pins.location.mapping.built_range). It is what a kept answer is keyed by: the pieces are a function of the
# build and of those lines, of nothing else (artifacts.RangeBoxCache).
BuiltRange: TypeAlias = Callable[[int, int], tuple[int, int] | None]
# The two askers of one file, bound together to one build's facts (limn.pins.location.resolve.RangeAsker): the lines
# the range is, then where they print.
MarkBinding: TypeAlias = tuple[BuiltRange, MarkRange]
# The caller's check on a file's lines as one answer reads them (today's lines, as read from the file): when it says
# no, the range is not measured. The pin consumer checks there that a stored pin's lines are still its text.
LinesHold: TypeAlias = Callable[[Sequence[str]], bool]
# Where a range of any file of one document prints: (the file's path on this machine, lo, hi, the caller's check of
# that file's lines) -> its pieces. This is what the pin consumer receives (limn.pins.needs.BoxesFor), bound to the
# build that document has on screen.
MarkBoxes: TypeAlias = Callable[[str, int, int, LinesHold], MarkPieces]
# The forward SyncTeX pass itself, which the pin consumer owns and the composition root injects
# (limn.pins.location.resolve.range_boxes): the document, a manuscript file, that file as the build read it (None when
# the build kept no record), the file as it is today, that build's PDF and every page of it as (width, height) in
# points -> the askers for the ranges of that file. Binding it once per file is what keeps the build facts read once.
MarkComputation: TypeAlias = Callable[
    [Doc, Path, Sequence[str] | None, Sequence[str], Path, Sequence[tuple[float, float]]], MarkBinding
]


@dataclass(frozen=True)
class DocumentBuildQueries:
    """Only the build queries used by document polling and outline reads."""

    summary: Callable[[Doc, Path, int], DocumentBuild]
    outline: Callable[[Doc], OutlineInput]


@dataclass(frozen=True)
class RevisionBuildQueries:
    """Only the build queries the changes view uses. history_files answers which files' Git history a document's changes
    are when they are a list of files - a figure document's map, the PDF its current build's map names and every script
    and shared component that map names; a Markdown or text document's own file - and None for a LaTeX document (its folder's
    manuscript suffixes) and a view-only PDF. overlay answers the two builds a figure document's changes view
    lays one over the other, as the completed JSON fragment {build, pages, prev_build, prev_pages}, and None for a
    document without an element map. No map, history entry or page folder crosses."""

    history_files: Callable[[Doc], tuple[Path, ...] | None]
    overlay: Callable[[Doc], dict[str, Any] | None]


@dataclass(frozen=True)
class PinBuildQueries:
    """Completed publication, source-equivalence and element answers for pin placement. page_root answers whether an
    element id is the root (the figure) of a page on a named build's map."""

    publication: Callable[[Doc, str, Path], Publication]
    position: Callable[[Doc], PositionHistory]
    heading: Callable[[Doc], BuildHeading]
    selection: Callable[[Doc, str, int, Frac], ElementSelection | SelectionUnavailable]
    elements: Callable[[Doc], ElementFollower | None]
    document_facts: Callable[[Doc, Path, Path, int], DocumentFacts]
    page_root: Callable[[Doc, str, int, str], bool]

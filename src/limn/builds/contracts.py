"""Purpose-specific build answers; no artifact layout or parsed map crosses this surface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

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
    """Detached, completed build-owned fields of the brief and meta HTTP contracts."""

    brief: dict[str, Any]
    meta: dict[str, Any]


@dataclass(frozen=True)
class Publication:
    """Assets and pick status of the selected build, never the mutable current pointer."""

    build: str
    pages: Path
    pdf: Path
    region_pdf: Path
    stale: bool
    running: bool
    latex_running: bool


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
    """One selected element's pin identity and source span, not a traversable map node."""

    id: str
    path: tuple[str, ...]
    label: str | None
    part: str | None
    impl: SourceLines | None
    frac: Frac
    source: SourceLines | None


@dataclass(frozen=True)
class ElementSelection:
    """Completed drag interpretation and nearest-first ladder in its chosen source file."""

    chosen: ElementFact
    kind: str
    score: float
    ladder: tuple[tuple[str, ElementFact], ...]


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


@dataclass(frozen=True)
class DocumentBuildQueries:
    """Only the build queries used by document polling and outline reads."""

    summary: Callable[[Doc, Path, int], DocumentBuild]
    outline: Callable[[Doc], OutlineInput]


@dataclass(frozen=True)
class PinBuildQueries:
    """Completed publication, source-equivalence and element answers for pin placement."""

    publication: Callable[[Doc, str, Path], Publication]
    position: Callable[[Doc], PositionHistory]
    heading: Callable[[Doc], BuildHeading]
    selection: Callable[[Doc, str, int, Frac], ElementSelection | SelectionUnavailable]
    elements: Callable[[Doc], ElementFollower | None]
    document_facts: Callable[[Doc, Path, Path, int], DocumentFacts]

"""Resolve a PDF drag to a source range or a view-only region."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from limn import build
from limn.documents import Doc, to_source
from limn.features.pins.location import source
from limn.features.pins.location.source import TokenCache
from limn.files import ManuscriptFile, file_in_tree, tex_lines
from limn.mapping import Traced, norm, snippet, trace_range, truncate_quote
from limn.pins.edit import PDF_QUOTE_MAX


class Selection(Protocol):
    """A validated drag (limn.features.pins.location.input.PickRequest): the page directory it is traced in, the page (1-based), the box
    (x0, y0, x1, y1) in points clamped to the page, the page size (width, height) in points, and the viewer's frac as
    sent (None if absent)."""

    @property
    def pdir(self) -> Path:
        """The page directory on screen at drag time."""
        ...

    @property
    def page(self) -> int:
        """The page, 1-based."""
        ...

    @property
    def box(self) -> tuple[float, float, float, float]:
        """x0, y0, x1, y1 in points."""
        ...

    @property
    def size(self) -> tuple[float, float]:
        """The page's width and height in points."""
        ...

    @property
    def frac(self) -> list[float] | None:
        """The viewer's page-relative box, or None."""
        ...


@dataclass(frozen=True)
class PickContext:
    """What resolving a selection needs from the instance: the manuscript root (a SyncTeX answer outside it is
    refused), the float environments of the range ladder (--float-envs), the state folder (for the "PDF older than the
    manuscript" check, and never part of the tree), the process's token-weight cache, and the overlaps of a range with the stored open pins
    (file, lo, hi) -> [{"id", "lo", "hi", "rel"}]."""

    root: Path
    envs: Sequence[str]
    state: Path
    tokens: TokenCache
    overlaps: Callable[[str, int, int], list[dict[str, Any]]]


@dataclass(frozen=True)
class Picked:
    """A selection traced to lines of a manuscript file: the file (inside the tree), the page, the range the paths
    agreed on (limn.mapping.Traced), the file's line count and the chosen range's text, the viewer's frac as sent, the
    region's printed text as a short quote, the stored open pins that range overlaps, and the page directory it was
    traced in. stale: the manuscript is newer than that build's PDF (by more than 2 s); building: a LaTeX build is
    running now. The location feature's HTTP answer turns this into the pick body."""

    file: Path
    page: int
    traced: Traced
    n_lines: int
    snippet: str
    frac: list[float] | None
    quote: str
    overlaps: list[dict[str, Any]]
    pdf_build: str
    stale: bool
    building: bool


@dataclass(frozen=True)
class PickedRegion:
    """A selection on a view-only PDF document: its key, the page and page-relative box (frac), the PDF's path from
    the manuscript root and file name, the region's printed text as a quote and its length, and the page directory.
    blank: the region has no printed text (a figure or scan); redrawing: the pages are being redrawn now."""

    doc: str
    page: int
    frac: list[float]
    pdf: str
    name: str
    quote: str
    n_chars: int
    blank: bool
    redrawing: bool
    pdf_build: str


@dataclass(frozen=True)
class GeneratedFile:
    """SyncTeX points into a generated file (a .bbl or .bib, by its suffix): the fix belongs in the .bib or the text."""

    suffix: str


@dataclass(frozen=True)
class SynctexOutside:
    """SyncTeX points at a file that is not in the manuscript tree (path as mapped back from the build copy)."""

    path: Path


@dataclass(frozen=True)
class SourceUnreadable:
    """The source file the selection lands in has no readable UTF-8 lines."""

    path: Path


@dataclass(frozen=True)
class NoSourceHere:
    """Neither SyncTeX nor the region's text leads to a line of the file."""


# Why a selection is not traced to manuscript lines; each is answered with its own 200 {"error", "reason"} body
# (limn.features.pins.location.http.PICK_REFUSALS).
PickRefusal: TypeAlias = GeneratedFile | SynctexOutside | SourceUnreadable | NoSourceHere


def pick(D: Doc, request: Selection, ctx: PickContext) -> Picked | PickedRegion | PickRefusal:
    """Dragged region -> source line range + range ladder, for document D and a selection parsed by
    limn.features.pins.location.input.parse_pick: a view-only document's region (PickedRegion), the traced range (Picked), or why the
    region cannot be traced to a manuscript line (PickRefusal).

    This is the shell: it runs pdftotext and SyncTeX on the build's PDF, maps SyncTeX's file back to the checkout,
    reads the file and weighs the region's tokens, then lets limn.mapping.trace_range choose between the two paths.
    The build facts (a manuscript newer than the PDF, a running LaTeX build) and the overlaps are read after that.

    The page directory is the build on screen at drag time (pdf_build, META.pages_build). A drag made after a rebuild
    finishes but before the viewer switches pages uses coordinates from the old layout, so it's traced back
    against that build's PDF and returned as pdf_build in the response - the viewer carries that value
    through unchanged when saving the pin (/api/pin) to record "which build's coordinates these are" (§Position estimation)."""
    pdir, page, (x0, y0, x1, y1), (pw, ph), frac = request.pdir, request.page, request.box, request.size, request.frac
    pdf = build.cur_pdf(D, pdir)
    rtext = source.region_text(pdf, page, x0, y0, x1, y1)
    if D.is_pdf:
        return _pick_region(D, pdir, page, (x0, y0, x1, y1), (pw, ph), frac, rtext)
    sy = source.by_synctex(pdf, page, x0, y0, x1, y1)

    src = to_source(D, sy[0]) if sy else D.main
    if src.suffix in (".bbl", ".bib"):
        return GeneratedFile(src.suffix)
    found = file_in_tree(str(src), ctx.root, ctx.state)
    if not isinstance(found, ManuscriptFile):
        return SynctexOutside(src)
    lines = tex_lines(found)
    if not lines:
        return SourceUnreadable(found.path)
    tw = ctx.tokens.weights(rtext, lines, source.file_key(found))
    traced = trace_range(tw, lines, (sy[1], sy[2]) if sy else None, ctx.envs)
    if traced is None:
        return NoSourceHere()

    stale = build.source_newer(D, ctx.state, pdir.name) > 2
    bstate = build.state_snapshot(D)
    return Picked(
        file=found.path,
        page=page,
        traced=traced,
        n_lines=len(lines),
        snippet=snippet(lines, traced.lo, traced.hi),
        frac=frac,
        quote=truncate_quote(norm(rtext), 60),
        overlaps=ctx.overlaps(str(found), traced.lo, traced.hi),
        pdf_build=pdir.name,
        stale=stale,
        building=bstate["state"] == "running" and bstate["phase"] == "latex",
    )


def _pick_region(
    D: Doc,
    pdir: Path,
    page: int,
    box: tuple[float, float, float, float],
    size: tuple[float, float],
    frac: list[float] | None,
    rtext: str,
) -> PickedRegion:
    """pick for a view-only document - only page/region and the region's text (pdftotext), no SyncTeX.
    If frac wasn't sent (agent curl), it's built from the coordinates - for a view-only pin, the region is the whole location."""
    x0, y0, x1, y1 = box
    pw, ph = size
    if frac is None:
        frac = [x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph]
    text = norm(rtext)
    bstate = build.state_snapshot(D)
    return PickedRegion(
        doc=D.key,
        page=page,
        frac=frac,
        pdf=D.rel_path(),
        name=D.main.name,
        quote=truncate_quote(text, PDF_QUOTE_MAX),
        n_chars=len(text),
        blank=not text,
        redrawing=bstate["state"] == "running",
        pdf_build=pdir.name,
    )
